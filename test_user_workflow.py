#!/usr/bin/env python3
"""
Test Script: User Creation and Deletion via Natural Language API

This script validates the complete workflow for creating and deleting users
through the AICMDEngine backend using natural language commands:

1. Authenticate with Membership Service
2. Plan user creation via natural language
3. Execute the creation plan
4. Verify user was created by listing members
5. Plan user deletion via natural language
6. Execute the deletion plan
7. Verify user was deleted

Test User: testuser333
Test Email: testuser333@example.com
"""

import httpx
import json
import asyncio
from typing import Optional, Dict, Any
from datetime import datetime

# Configuration
MEMBERSHIP_SERVICE_URL = "http://localhost:8080"
BACKEND_API_URL = "http://localhost:8000/v1"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"
TENANT_ID = 1
TEST_USERNAME = "testuser333"
TEST_EMAIL = "testuser333@example.com"
TEST_PASSWORD = "testpass123"

# Test results tracking
class TestResults:
    def __init__(self):
        self.tests = []
        self.start_time = datetime.now()

    def add_result(self, step: str, status: str, details: str, response_data: Optional[Dict] = None):
        """Add a test result"""
        self.tests.append({
            "step": step,
            "status": status,  # "PASS" or "FAIL"
            "details": details,
            "response": response_data,
            "timestamp": datetime.now().isoformat()
        })

    def print_summary(self):
        """Print test results summary"""
        print("\n" + "=" * 80)
        print("TEST RESULTS SUMMARY")
        print("=" * 80)

        passed = sum(1 for t in self.tests if t["status"] == "PASS")
        failed = sum(1 for t in self.tests if t["status"] == "FAIL")
        total = len(self.tests)

        print(f"\nTotal Tests: {total} | Passed: {passed} | Failed: {failed}")
        print("-" * 80)

        for i, test in enumerate(self.tests, 1):
            status_icon = "✅" if test["status"] == "PASS" else "❌"
            print(f"\n{i}. {test['step']} {status_icon}")
            print(f"   Status: {test['status']}")
            print(f"   Details: {test['details']}")
            if test["response"]:
                print(f"   Response: {json.dumps(test['response'], indent=6)[:300]}...")

        print("\n" + "=" * 80)
        duration = (datetime.now() - self.start_time).total_seconds()
        print(f"Total Duration: {duration:.2f}s")
        print("=" * 80 + "\n")

results = TestResults()

async def step_1_authenticate():
    """Step 1: Get access token from Membership Service"""
    print("\n[Step 1] Authenticating with Membership Service...")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{MEMBERSHIP_SERVICE_URL}/v2/auth/login",
                json={
                    "username": ADMIN_USERNAME,
                    "password": ADMIN_PASSWORD
                },
                timeout=10.0
            )

            if response.status_code == 200:
                data = response.json()
                access_token = data.get("access_token")

                if access_token:
                    print(f"✅ Authentication successful")
                    print(f"   Token: {access_token[:50]}...")
                    results.add_result(
                        "Step 1: Authenticate with Membership Service",
                        "PASS",
                        f"Got access token for user: {ADMIN_USERNAME}",
                        data
                    )
                    return access_token
                else:
                    print(f"❌ No access token in response")
                    results.add_result(
                        "Step 1: Authenticate with Membership Service",
                        "FAIL",
                        "No access_token field in response",
                        data
                    )
                    return None
            else:
                print(f"❌ Authentication failed: HTTP {response.status_code}")
                print(f"   Response: {response.text}")
                results.add_result(
                    "Step 1: Authenticate with Membership Service",
                    "FAIL",
                    f"HTTP {response.status_code}: {response.text}",
                    None
                )
                return None

    except Exception as e:
        print(f"❌ Authentication error: {str(e)}")
        results.add_result(
            "Step 1: Authenticate with Membership Service",
            "FAIL",
            f"Exception: {str(e)}",
            None
        )
        return None

async def step_2_plan_creation(access_token: str):
    """Step 2: Plan user creation via natural language"""
    print("\n[Step 2] Planning user creation via natural language...")

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            goal = f"Create a new user {TEST_USERNAME} with email {TEST_EMAIL}"

            response = await client.post(
                f"{BACKEND_API_URL}/tasks/",
                json={
                    "goal": goal,
                    "conversationHistory": []
                },
                headers={
                    "X-Tenant-ID": str(TENANT_ID),
                    "Content-Type": "application/json"
                },
                follow_redirects=True
            )

            if response.status_code == 200:
                data = response.json()
                response_type = data.get("type")

                if response_type == "plan_ready":
                    plan = data.get("plan")
                    print(f"✅ Plan generated successfully")
                    print(f"   Plan steps: {len(plan) if plan else 0}")
                    if plan:
                        for i, step in enumerate(plan, 1):
                            print(f"   Step {i}: {step.get('command', 'N/A')}")

                    results.add_result(
                        "Step 2: Plan user creation",
                        "PASS",
                        f"Plan with {len(plan) if plan else 0} steps generated for goal: {goal}",
                        data
                    )
                    return plan

                elif response_type == "clarification_needed":
                    print(f"❌ Clarification needed from LLM")
                    clarification = data.get("clarification", "No details")
                    print(f"   Clarification: {clarification}")
                    results.add_result(
                        "Step 2: Plan user creation",
                        "FAIL",
                        f"Clarification needed: {clarification}",
                        data
                    )
                    return None

                else:
                    print(f"❌ Unexpected response type: {response_type}")
                    results.add_result(
                        "Step 2: Plan user creation",
                        "FAIL",
                        f"Unexpected response type: {response_type}",
                        data
                    )
                    return None
            else:
                print(f"❌ Plan creation failed: HTTP {response.status_code}")
                print(f"   Response: {response.text}")
                results.add_result(
                    "Step 2: Plan user creation",
                    "FAIL",
                    f"HTTP {response.status_code}: {response.text}",
                    None
                )
                return None

    except Exception as e:
        print(f"❌ Plan creation error: {str(e)}")
        results.add_result(
            "Step 2: Plan user creation",
            "FAIL",
            f"Exception: {str(e)}",
            None
        )
        return None

async def step_3_execute_creation(plan: list, access_token: str):
    """Step 3: Execute the creation plan"""
    print("\n[Step 3] Executing user creation plan...")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{BACKEND_API_URL}/executions/",
                json={
                    "plan": plan,
                    "global_timeout": 60
                },
                headers={
                    "X-Tenant-ID": str(TENANT_ID),
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                },
                timeout=30.0,
                follow_redirects=True
            )

            if response.status_code == 200:
                data = response.json()
                execution_id = data.get("execution_id")
                status = data.get("status")

                print(f"✅ Execution initiated")
                print(f"   Execution ID: {execution_id}")
                print(f"   Status: {status}")

                results.add_result(
                    "Step 3: Execute creation plan",
                    "PASS",
                    f"Execution {execution_id} status: {status}",
                    data
                )

                # Poll for execution completion
                print(f"   Waiting for execution to complete...")
                max_retries = 15
                retry_count = 0
                while retry_count < max_retries:
                    await asyncio.sleep(1)
                    retry_count += 1

                    # Check execution status
                    status_response = await client.get(
                        f"{BACKEND_API_URL}/executions/{execution_id}",
                        headers={
                            "X-Tenant-ID": str(TENANT_ID),
                        },
                        timeout=10.0
                    )

                    if status_response.status_code == 200:
                        status_data = status_response.json()
                        current_status = status_data.get("status")
                        print(f"   Status check {retry_count}/{max_retries}: {current_status}")

                        if current_status in ["completed", "failed"]:
                            print(f"   Execution finished with status: {current_status}")
                            if current_status == "failed":
                                # Print error details
                                steps = status_data.get("steps", [])
                                for step in steps:
                                    if step.get("status") == "failed":
                                        print(f"     Step {step.get('step')}: {step.get('error', 'No error message')}")
                            break
                    else:
                        print(f"   Status check failed: HTTP {status_response.status_code}")

                return execution_id
            else:
                print(f"❌ Execution failed: HTTP {response.status_code}")
                print(f"   Response: {response.text}")
                results.add_result(
                    "Step 3: Execute creation plan",
                    "FAIL",
                    f"HTTP {response.status_code}: {response.text}",
                    None
                )
                return None

    except Exception as e:
        print(f"❌ Execution error: {str(e)}")
        results.add_result(
            "Step 3: Execute creation plan",
            "FAIL",
            f"Exception: {str(e)}",
            None
        )
        return None

async def step_4_verify_creation(access_token: str):
    """Step 4: Verify user was created by listing members"""
    print("\n[Step 4] Verifying user creation by listing members...")

    try:
        async with httpx.AsyncClient() as client:
            # Try to get members list from Membership Service
            response = await client.get(
                f"{MEMBERSHIP_SERVICE_URL}/v2/members",
                headers={
                    "X-Tenant-ID": str(TENANT_ID),
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                },
                timeout=10.0
            )

            if response.status_code == 200:
                data = response.json()
                members = data.get("data", []) if isinstance(data, dict) else data

                # Check if our test user is in the list
                test_user_found = False
                if isinstance(members, list):
                    for member in members:
                        if isinstance(member, dict) and member.get("username") == TEST_USERNAME:
                            test_user_found = True
                            print(f"✅ Test user found in members list")
                            print(f"   Username: {member.get('username')}")
                            print(f"   Email: {member.get('email')}")
                            break

                if test_user_found:
                    results.add_result(
                        "Step 4: Verify user creation",
                        "PASS",
                        f"User {TEST_USERNAME} found in members list",
                        data
                    )
                    return True
                else:
                    print(f"❌ Test user not found in members list")
                    print(f"   Total members: {len(members) if isinstance(members, list) else 'unknown'}")
                    results.add_result(
                        "Step 4: Verify user creation",
                        "FAIL",
                        f"User {TEST_USERNAME} not found in members list",
                        data
                    )
                    return False
            else:
                print(f"❌ Members list failed: HTTP {response.status_code}")
                print(f"   Response: {response.text}")
                results.add_result(
                    "Step 4: Verify user creation",
                    "FAIL",
                    f"HTTP {response.status_code}: {response.text}",
                    None
                )
                return False

    except Exception as e:
        print(f"❌ Verification error: {str(e)}")
        results.add_result(
            "Step 4: Verify user creation",
            "FAIL",
            f"Exception: {str(e)}",
            None
        )
        return False

async def step_5_plan_deletion(access_token: str):
    """Step 5: Plan user deletion via natural language"""
    print("\n[Step 5] Planning user deletion via natural language...")

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            # First, get the user ID from member list
            list_response = await client.get(
                f"{MEMBERSHIP_SERVICE_URL}/v2/members",
                headers={
                    "X-Tenant-ID": str(TENANT_ID),
                    "Authorization": f"Bearer {access_token}",
                },
                timeout=10.0
            )

            user_id = None
            if list_response.status_code == 200:
                members_data = list_response.json()
                members = members_data.get("data", [])
                for member in members:
                    if member.get("username") == TEST_USERNAME:
                        user_id = member.get("id")
                        print(f"   Found user ID: {user_id}")
                        break

            if not user_id:
                print(f"❌ Could not find user ID for {TEST_USERNAME}")
                results.add_result(
                    "Step 5: Plan user deletion",
                    "FAIL",
                    f"Could not find user ID for {TEST_USERNAME}",
                    None
                )
                return None

            # Now plan the deletion with the user ID
            goal = f"Delete the user with ID {user_id} (username: {TEST_USERNAME})"

            response = await client.post(
                f"{BACKEND_API_URL}/tasks/",
                json={
                    "goal": goal,
                    "conversationHistory": []
                },
                headers={
                    "X-Tenant-ID": str(TENANT_ID),
                    "Content-Type": "application/json"
                },
                follow_redirects=True
            )

            if response.status_code == 200:
                data = response.json()
                response_type = data.get("type")

                if response_type == "plan_ready":
                    plan = data.get("plan")
                    print(f"✅ Deletion plan generated successfully")
                    print(f"   Plan steps: {len(plan) if plan else 0}")
                    if plan:
                        for i, step in enumerate(plan, 1):
                            print(f"   Step {i}: {step.get('command', 'N/A')}")

                    results.add_result(
                        "Step 5: Plan user deletion",
                        "PASS",
                        f"Plan with {len(plan) if plan else 0} steps generated for goal: {goal}",
                        data
                    )
                    return plan

                elif response_type == "clarification_needed":
                    print(f"❌ Clarification needed from LLM")
                    clarification = data.get("clarification", "No details")
                    results.add_result(
                        "Step 5: Plan user deletion",
                        "FAIL",
                        f"Clarification needed: {clarification}",
                        data
                    )
                    return None

                else:
                    print(f"❌ Unexpected response type: {response_type}")
                    results.add_result(
                        "Step 5: Plan user deletion",
                        "FAIL",
                        f"Unexpected response type: {response_type}",
                        data
                    )
                    return None
            else:
                print(f"❌ Plan deletion failed: HTTP {response.status_code}")
                print(f"   Response: {response.text}")
                results.add_result(
                    "Step 5: Plan user deletion",
                    "FAIL",
                    f"HTTP {response.status_code}: {response.text}",
                    None
                )
                return None

    except Exception as e:
        print(f"❌ Plan deletion error: {str(e)}")
        results.add_result(
            "Step 5: Plan user deletion",
            "FAIL",
            f"Exception: {str(e)}",
            None
        )
        return None

async def step_6_execute_deletion(plan: list, access_token: str):
    """Step 6: Execute the deletion plan"""
    print("\n[Step 6] Executing user deletion plan...")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{BACKEND_API_URL}/executions/",
                json={
                    "plan": plan,
                    "global_timeout": 60
                },
                headers={
                    "X-Tenant-ID": str(TENANT_ID),
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                },
                timeout=30.0,
                follow_redirects=True
            )

            if response.status_code == 200:
                data = response.json()
                execution_id = data.get("execution_id")
                status = data.get("status")

                print(f"✅ Deletion execution initiated")
                print(f"   Execution ID: {execution_id}")
                print(f"   Status: {status}")

                results.add_result(
                    "Step 6: Execute deletion plan",
                    "PASS",
                    f"Execution {execution_id} status: {status}",
                    data
                )

                # Poll for execution completion
                print(f"   Waiting for deletion execution to complete...")
                max_retries = 15
                retry_count = 0
                while retry_count < max_retries:
                    await asyncio.sleep(1)
                    retry_count += 1

                    # Check execution status
                    status_response = await client.get(
                        f"{BACKEND_API_URL}/executions/{execution_id}",
                        headers={
                            "X-Tenant-ID": str(TENANT_ID),
                        },
                        timeout=10.0
                    )

                    if status_response.status_code == 200:
                        status_data = status_response.json()
                        current_status = status_data.get("status")
                        print(f"   Status check {retry_count}/{max_retries}: {current_status}")

                        if current_status in ["completed", "failed"]:
                            print(f"   Deletion execution finished with status: {current_status}")
                            break
                    else:
                        print(f"   Status check failed: HTTP {status_response.status_code}")

                return execution_id
            else:
                print(f"❌ Deletion execution failed: HTTP {response.status_code}")
                print(f"   Response: {response.text}")
                results.add_result(
                    "Step 6: Execute deletion plan",
                    "FAIL",
                    f"HTTP {response.status_code}: {response.text}",
                    None
                )
                return None

    except Exception as e:
        print(f"❌ Deletion execution error: {str(e)}")
        results.add_result(
            "Step 6: Execute deletion plan",
            "FAIL",
            f"Exception: {str(e)}",
            None
        )
        return None

async def step_7_verify_deletion(access_token: str):
    """Step 7: Verify user was deleted"""
    print("\n[Step 7] Verifying user deletion by listing members...")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{MEMBERSHIP_SERVICE_URL}/v2/members",
                headers={
                    "X-Tenant-ID": str(TENANT_ID),
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                },
                timeout=10.0
            )

            if response.status_code == 200:
                data = response.json()
                members = data.get("data", []) if isinstance(data, dict) else data

                # Check that our test user is NOT in the list
                test_user_found = False
                if isinstance(members, list):
                    for member in members:
                        if isinstance(member, dict) and member.get("username") == TEST_USERNAME:
                            test_user_found = True
                            break

                if not test_user_found:
                    print(f"✅ Test user successfully deleted")
                    print(f"   Total members: {len(members) if isinstance(members, list) else 'unknown'}")
                    results.add_result(
                        "Step 7: Verify user deletion",
                        "PASS",
                        f"User {TEST_USERNAME} no longer in members list",
                        data
                    )
                    return True
                else:
                    print(f"❌ Test user still exists in members list")
                    results.add_result(
                        "Step 7: Verify user deletion",
                        "FAIL",
                        f"User {TEST_USERNAME} still exists in members list",
                        data
                    )
                    return False
            else:
                print(f"❌ Members list failed: HTTP {response.status_code}")
                print(f"   Response: {response.text}")
                results.add_result(
                    "Step 7: Verify user deletion",
                    "FAIL",
                    f"HTTP {response.status_code}: {response.text}",
                    None
                )
                return False

    except Exception as e:
        print(f"❌ Deletion verification error: {str(e)}")
        results.add_result(
            "Step 7: Verify user deletion",
            "FAIL",
            f"Exception: {str(e)}",
            None
        )
        return False

async def main():
    """Run all test steps"""
    print("\n" + "=" * 80)
    print("USER CREATION/DELETION WORKFLOW TEST")
    print("=" * 80)
    print(f"Test User: {TEST_USERNAME}")
    print(f"Test Email: {TEST_EMAIL}")
    print(f"Backend API: {BACKEND_API_URL}")
    print(f"Membership Service: {MEMBERSHIP_SERVICE_URL}")
    print(f"Tenant ID: {TENANT_ID}")
    print("=" * 80)

    # Step 1: Authenticate
    access_token = await step_1_authenticate()
    if not access_token:
        print("\n❌ Authentication failed. Stopping test.")
        results.print_summary()
        return

    # Step 2: Plan creation
    creation_plan = await step_2_plan_creation(access_token)
    if not creation_plan:
        print("\n❌ Plan creation failed. Stopping test.")
        results.print_summary()
        return

    # Step 3: Execute creation
    creation_execution_id = await step_3_execute_creation(creation_plan, access_token)
    if not creation_execution_id:
        print("\n❌ Creation execution failed. Stopping test.")
        results.print_summary()
        return

    # Step 4: Verify creation
    creation_verified = await step_4_verify_creation(access_token)
    if not creation_verified:
        print("\n❌ Creation verification failed. Test user was not created.")
        results.print_summary()
        return

    # Step 5: Plan deletion
    deletion_plan = await step_5_plan_deletion(access_token)
    if not deletion_plan:
        print("\n⚠️  Plan deletion failed. Skipping deletion test.")
        results.print_summary()
        return

    # Step 6: Execute deletion
    deletion_execution_id = await step_6_execute_deletion(deletion_plan, access_token)
    if not deletion_execution_id:
        print("\n❌ Deletion execution failed.")
        results.print_summary()
        return

    # Step 7: Verify deletion
    deletion_verified = await step_7_verify_deletion(access_token)

    # Print final summary
    results.print_summary()

if __name__ == "__main__":
    asyncio.run(main())
