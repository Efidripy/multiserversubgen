#!/usr/bin/env python3
"""
E2E WebSocket test for vm1 realtime updates.
Tests that WebSocket connection can be established and broadcast messages received.
"""
import asyncio
import json
import sys
import base64
from datetime import datetime

try:
    import websockets
except ImportError:
    print("ERROR: websockets not installed. Install with: pip install websockets")
    sys.exit(1)


async def test_websocket_connection(host="vm1.kleva.ru", port=666, auth_user="test", auth_pass="test"):
    """
    Test WebSocket connection to vm1 realtime endpoint.
    """
    
    credentials = f"{auth_user}:{auth_pass}"
    auth_b64 = base64.b64encode(credentials.encode()).decode()
    
    # Try via wss:// first, fall back to ws://
    for proto in ["wss", "ws"]:
        uri = f"{proto}://{host}:{port}/ws"
        
        print(f"[{datetime.now().isoformat()}] Attempting WebSocket connection to {uri}")
        print(f"  Auth: {auth_user}:{'*' * len(auth_pass)}")
        
        try:
            # Note: For FastAPI WebSocket with custom auth, the token typically needs to be
            # passed as a query parameter, not a header. The backend routing handles it.
            ssl_context = None
            if proto == "wss":
                import ssl
                ssl_context = ssl.SSLContext()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
            
            async with websockets.connect(uri, ssl=ssl_context) as ws:
                print(f"[{datetime.now().isoformat()}] ✓ Connected!")
                
                # Subscribe to traffic updates
                subscribe_msg = {
                    "type": "subscribe",
                    "channels": ["traffic", "clients", "server_status"]
                }
                print(f"[{datetime.now().isoformat()}] Subscribing to channels: {subscribe_msg['channels']}")
                await ws.send(json.dumps(subscribe_msg))
                
                # Listen for messages (timeout after 10 seconds)
                start_time = datetime.now()
                timeout_seconds = 10
                message_count = 0
                
                while True:
                    elapsed = (datetime.now() - start_time).total_seconds()
                    if elapsed > timeout_seconds:
                        print(f"[{datetime.now().isoformat()}] Timeout reached ({timeout_seconds}s), closing connection")
                        break
                    
                    try:
                        # Set timeout for receive
                        msg_text = await asyncio.wait_for(ws.recv(), timeout=1.0)
                        message_count += 1
                        
                        try:
                            msg = json.loads(msg_text)
                            msg_type = msg.get("type", "unknown")
                            print(f"[{datetime.now().isoformat()}] Message #{message_count}: type={msg_type}, keys={list(msg.keys())[:5]}...")
                            
                            if msg_type == "error":
                                print(f"  ERROR MESSAGE: {msg.get('message', 'unknown error')}")
                            elif msg_type in ["traffic_update", "client_update", "server_status"]:
                                print(f"  ✓ Received broadcast: {msg_type}")
                        except json.JSONDecodeError:
                            print(f"[{datetime.now().isoformat()}] Message #{message_count}: (non-JSON) {msg_text[:100]}")
                            
                    except asyncio.TimeoutError:
                        # No message in that 1s window, keep waiting up to timeout_seconds
                        if message_count == 0:
                            print(f"[{datetime.now().isoformat()}] Waiting for broadcasts... ({int(elapsed)}/{timeout_seconds}s)")
                        continue
                
                print(f"[{datetime.now().isoformat()}] ✓ Test complete. Received {message_count} message(s).")
                return message_count > 0
                
        except websockets.exceptions.WebSocketException as e:
            print(f"[{datetime.now().isoformat()}] ✗ WebSocket error on {proto}://: {e}")
            continue
        except Exception as e:
            print(f"[{datetime.now().isoformat()}] ✗ Connection error on {proto}://: {type(e).__name__}: {e}")
            continue
    
    print(f"[{datetime.now().isoformat()}] ✗ All connection attempts failed")
    return False


async def main():
    """Run tests."""
    
    # Test 1: Connection to vm1
    print("\n=== TEST 1: WebSocket Connection to vm1 ===")
    success = await test_websocket_connection(host="vm1.kleva.ru", port=666)
    
    if success:
        print("\n✓ E2E WebSocket test PASSED")
        return 0
    else:
        print("\n✗ E2E WebSocket test FAILED")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
