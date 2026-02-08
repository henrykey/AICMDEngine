#!/usr/bin/env python3

import asyncio
import sys
import os
import json

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from pymongo import MongoClient
from datetime import datetime

# Connect to MongoDB
client = MongoClient('mongodb://localhost:27017/')
db = client['aicmdb']

# Check the specific execution
execution_id = '697616f7c42aa46263a3ef44'
execution = db['executions'].find_one({"_id": execution_id})

print("=== EXECUTION DETAILS ===")
print(f"Execution ID: {execution['_id']}")
print(f"Status: {execution.get('status')}")
print(f"Total Steps: {execution.get('total_steps')}")
print(f"Completed Steps: {execution.get('completed_steps')}")
print(f"Failed Steps: {execution.get('failed_steps')}")
print(f"Started At: {execution.get('started_at')}")
print(f"Completed At: {execution.get('completed_at')}")
print(f"Error Message: {execution.get('error_message')}")
print("\n=== STEPS ===")

# Find all steps for this execution
steps = db['execution_steps'].find({"execution_id": execution_id}).sort("step_number", 1)

for step in steps:
    print(f"\nStep {step.get('step_number')}:")
    print(f"  Status: {step.get('status')}")
    print(f"  Command: {step.get('command')}")
    print(f"  Started At: {step.get('started_at')}")
    print(f"  Completed At: {step.get('completed_at')}")
    print(f"  Error Message: {step.get('error_message')}")

    # Check if there are results
    if 'results' in step and step['results']:
        print(f"  Results: {json.dumps(step['results'], indent=2)}")
    else:
        print("  Results: No results found")

    # Check if there's output
    if 'output' in step and step['output']:
        print(f"  Output: {step['output']}")

# Check the audit logs
print("\n=== AUDIT LOGS ===")
audit_logs = db['audit_logs'].find({"execution_id": execution_id}).sort("timestamp", 1)

for log in audit_logs:
    print(f"{log.get('timestamp')} - {log.get('action')}: {log.get('category')}")

client.close()