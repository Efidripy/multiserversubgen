#!/bin/bash

# Quick test for server addition data flow on vm1
# Usage: bash test-server-addition-flow.sh

set -e

PANEL_URL="https://localhost:666"
ADMIN_USER="admin"
ADMIN_PASS="password"
CURL_OPTS="-s -u ${ADMIN_USER}:${ADMIN_PASS} -k -H 'Content-Type: application/json'"

echo "=== Testing Server Addition Data Flow on vm1 ==="

# Check panel is running
echo "[1/6]  Checking if panel is running..."
if ! systemctl is-active --quiet sub-manager; then
    echo "ERROR: sub-manager service is not running"
    exit 1
fi
echo "✓ Panel is running"

# Test basic API access
echo "[2/6] Testing basic API access..."
if ! curl ${CURL_OPTS} "${PANEL_URL}/api/v1/nodes" > /dev/null 2>&1; then
    echo "ERROR: Cannot reach API"
    exit 1
fi
echo "✓ API is accessible"

# Get initial node count
echo "[3/6] Getting initial node count..."
INITIAL_NODES=$(curl ${CURL_OPTS} "${PANEL_URL}/api/v1/nodes" 2>/dev/null | jq 'length // 0' || echo "0")
echo "Initial nodes: $INITIAL_NODES"

# Add test server
echo "[4/6] Adding test server..."
TEST_SERVER=$(cat <<EOF
{
  "name": "test-flow-$(date +%s)",
  "url": "https://127.0.0.1:8443/panel",
  "user": "test_user",
  "password": "test_pass"
}
EOF
)

ADD_RESPONSE=$(curl ${CURL_OPTS} -X POST \
  -d "$TEST_SERVER" \
  "${PANEL_URL}/api/v1/nodes" 2>/dev/null)
echo "Add response: $ADD_RESPONSE"

# Get node list and check what was stored
echo "[5/6] Fetching node list to verify storage..."
NODES_LIST=$(curl ${CURL_OPTS} "${PANEL_URL}/api/v1/nodes" 2>/dev/null | jq '.' || echo "[]")
FINAL_COUNT=$(echo "$NODES_LIST" | jq 'length // 0')
echo "Final node count: $FINAL_COUNT"

if [ "$FINAL_COUNT" -gt "$INITIAL_NODES" ]; then
    echo "✓ Node was added"
    LAST_NODE=$(echo "$NODES_LIST" | jq '.[-1]')
    echo "Last node added:"
    echo "$LAST_NODE" | jq '.'
    NODE_ID=$(echo "$LAST_NODE" | jq '.id')
    echo "Node ID: $NODE_ID"
else
    echo "✗ Node was NOT added - something went wrong"
    echo "Response was: $ADD_RESPONSE"
fi

# Check database directly
echo "[6/6] Checking database..."
echo "Nodes table content:"
sqlite3 /opt/sub-manager/admin.db "SELECT id, name, ip, port, base_path FROM nodes ORDER BY id DESC LIMIT 3;" 2>/dev/null || echo "Cannot access database"

echo ""
echo "=== Test Complete ==="
echo "✓ If you see node data above, the addition flow is working"
echo "✗ If data looks corrupted or missing, there's a linking issue"
