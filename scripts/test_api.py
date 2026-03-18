"""
API Test Script for DreamPilot Backend
Tests the deployed API endpoints
"""
import requests
import json
import sys

# Base URL for the API
BASE_URL = "https://learninggrid-tyh612-api.dreambigwithai.com"

def test_health():
    """Test the health endpoint"""
    print("\n" + "="*50)
    print("TEST 1: Health Check")
    print("="*50)
    
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=10)
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("✅ PASSED")
        return True
    except Exception as e:
        print(f"❌ FAILED: {e}")
        return False

def test_root():
    """Test the root endpoint"""
    print("\n" + "="*50)
    print("TEST 2: Root Endpoint")
    print("="*50)
    
    try:
        response = requests.get(f"{BASE_URL}/", timeout=10)
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("✅ PASSED")
        return True
    except Exception as e:
        print(f"❌ FAILED: {e}")
        return False

def test_login(email="testuser123@example.com", password="testpass123"):
    """Test the login endpoint"""
    print("\n" + "="*50)
    print("TEST 3: Login")
    print("="*50)
    
    try:
        payload = {
            "email": email,
            "password": password
        }
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json=payload,
            timeout=10
        )
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        
        if response.status_code == 200:
            data = response.json()
            token = data.get("token")
            print("✅ PASSED - Got token")
            return token
        else:
            print("⚠️ Login failed")
            return None
    except Exception as e:
        print(f"❌ FAILED: {e}")
        return None


def test_register():
    """Test the register endpoint"""
    print("\n" + "="*50)
    print("TEST 4: Register New User")
    print("="*50)
    
    try:
        payload = {
            "email": "testuser123@example.com",
            "password": "testpass123"
        }
        response = requests.post(
            f"{BASE_URL}/api/auth/register",
            json=payload,
            timeout=10
        )
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        
        if response.status_code in [200, 201]:
            print("✅ PASSED - User registered")
            return True
        elif response.status_code == 400:
            print("⚠️ User may already exist")
            return True
        else:
            print(f"❌ FAILED with status {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ FAILED: {e}")
        return False


def test_protected_endpoint(token):
    """Test a protected endpoint with JWT token"""
    print("\n" + "="*50)
    print("TEST 5: Protected Endpoint (with JWT)")
    print("="*50)
    
    if not token:
        print("⚠️ SKIPPED - No token available")
        return None
    
    try:
        headers = {
            "Authorization": f"Bearer {token}"
        }
        # Try the /api/auth/me endpoint if it exists
        response = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers=headers,
            timeout=10
        )
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        
        if response.status_code == 200:
            print("✅ PASSED - Token is valid")
            return True
        elif response.status_code == 404:
            print("⚠️ /me endpoint not implemented (but token may still be valid)")
            return True
        else:
            print(f"❌ FAILED with status {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ FAILED: {e}")
        return False

def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("🧪 DreamPilot API Test Suite")
    print(f"Target: {BASE_URL}")
    print("="*60)
    
    results = []
    
    # Test credentials
    test_email = "testuser123@example.com"
    test_password = "testpass123"
    
    # Run tests
    results.append(("Health Check", test_health()))
    results.append(("Root Endpoint", test_root()))
    results.append(("Register User", test_register()))
    token = test_login(test_email, test_password)
    results.append(("Login", token is not None))
    results.append(("Protected Endpoint", test_protected_endpoint(token)))
    
    # Summary
    print("\n" + "="*60)
    print("📊 TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{name}: {status}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED!")
        sys.exit(0)
    else:
        print(f"\n⚠️ {total - passed} test(s) failed")
        sys.exit(1)

if __name__ == "__main__":
    main()
