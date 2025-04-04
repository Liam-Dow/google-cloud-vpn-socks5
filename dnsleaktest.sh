#!/usr/bin/env bash
# Usage:   ./dnsleaktest.sh [-i interface|proxy]
# Example: ./dnsleaktest.sh -i eth1
#          ./dnsleaktest.sh -i 10.0.0.2
#          ./dnsleaktest.sh -i socks5h://10.0.0.1:1080

RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'
api_domain='bash.ws'
error_code=1

getopts "i:" opt
input=$OPTARG

function echo_bold {
    echo -e "${BOLD}${1}${NC}"
}

function echo_error {
    (>&2 echo -e "${RED}${1}${NC}")
}

function increment_error_code {
    error_code=$((error_code + 1))
}

function require_command {
    command -v $1 > /dev/null
    if [ $? -ne 0 ]; then
        echo_error "Please install \"$1\""
        exit $error_code
    fi
    increment_error_code
}

require_command curl
require_command ping

# Determine if input is a proxy (starts with protocol://) or interface/IP
if [[ "$input" =~ ^(socks5h?|http|https):// ]]; then
    proxy_mode=1
    curl_option="--proxy ${input}"
    ping_interface=""  # ping doesn't use proxies
    echo_bold "Using proxy: ${input}"
else
    proxy_mode=0
    curl_option="--interface ${input}"
    ping_interface="-I ${input}"
    echo_bold "Using interface/IP: ${input}"
fi
echo ""

function check_internet_connection {
    curl --silent --head ${curl_option} --request GET "https://${api_domain}" | grep "200 OK" > /dev/null
    if [ $? -ne 0 ]; then
        echo_error "No internet connection."
        exit $error_code
    fi
    increment_error_code
}

check_internet_connection

if command -v jq &> /dev/null; then
    jq_exists=1
else
    jq_exists=0
fi

id=$(curl ${curl_option} --silent "https://${api_domain}/id")

for i in $(seq 1 10); do
    ping -c 1 ${ping_interface} "${i}.${id}.${api_domain}" > /dev/null 2>&1
done

function print_servers {
    if (( $jq_exists )); then
        echo ${result_json} | jq --monochrome-output --raw-output \
            ".[] | select(.type == \"${1}\") | \"\(.ip)\(if .country_name != \"\" and  .country_name != false then \" [\(.country_name)\(if .asn != \"\" and .asn != false then \" \(.asn)\" else \"\" end)]\" else \"\" end)\""
    else
        while IFS= read -r line; do
            if [[ "$line" != *${1} ]]; then
                continue
            fi
            ip=$(echo $line | cut -d'|' -f 1)
            country=$(echo $line | cut -d'|' -f 3)
            asn=$(echo $line | cut -d'|' -f 4)
            if [ -z "${ip// }" ]; then continue; fi
            if [ -z "${country// }" ]; then
                echo "$ip"
            else
                if [ -z "${asn// }" ]; then
                    echo "$ip [$country]"
                else
                    echo "$ip [$country, $asn]"
                fi
            fi
        done <<< "$result_txt"
    fi
}

if (( $jq_exists )); then
    result_json=$(curl ${curl_option} --silent "https://${api_domain}/dnsleak/test/${id}?json")
else
    result_txt=$(curl ${curl_option} --silent "https://${api_domain}/dnsleak/test/${id}?txt")
fi

dns_count=$(print_servers "dns" | wc -l)

echo_bold "Your IP:"
print_servers "ip"
echo ""

if [ ${dns_count} -eq "0" ]; then
    echo_bold "No DNS servers found"
else
    if [ ${dns_count} -eq "1" ]; then
        echo_bold "You use ${dns_count} DNS server:"
    else
        echo_bold "You use ${dns_count} DNS servers:"
    fi
    print_servers "dns"
fi

echo ""
echo_bold "Conclusion:"
print_servers "conclusion"

exit 0
