#!/bin/bash
# Test script to run harden CLI on all synthetic apps
# Usage: ./test_all_apps.sh

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

echo "==================================="
echo "Testing Harden CLI on Synthetic Apps"
echo "==================================="
echo ""

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Counter
total=0
passed=0
failed=0

# Test each app
for app_dir in app01_* app02_* app03_* app04_* app05_* app06_* app07_* app08_* app09_* app10_*; do
    if [ -d "$app_dir" ]; then
        total=$((total + 1))
        echo "[$total] Testing $app_dir..."

        cd "$app_dir"

        # Run harden analyze
        if harden analyze > /dev/null 2>&1; then
            echo -e "  ${GREEN}✓${NC} Analysis completed"
            passed=$((passed + 1))
        else
            echo -e "  ${RED}✗${NC} Analysis failed"
            failed=$((failed + 1))
        fi

        cd "$SCRIPT_DIR"
        echo ""
    fi
done

echo "==================================="
echo "Summary:"
echo "  Total apps: $total"
echo -e "  ${GREEN}Passed: $passed${NC}"
echo -e "  ${RED}Failed: $failed${NC}"
echo "==================================="

if [ $failed -eq 0 ]; then
    exit 0
else
    exit 1
fi
