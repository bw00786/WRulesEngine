import requests
import concurrent.futures
import time
import random

# Configuration
API_URL = "http://localhost:8000/evaluate/"
NUM_USERS = 50000000  # Number of concurrent users
FACTS_LIST = [
    {"debt_to_income_ratio": 55, "credit_score": 700, "employment_status": "employed"},
    {"debt_to_income_ratio": 45, "credit_score": 650, "employment_status": "unemployed"},
    {"debt_to_income_ratio": 60, "credit_score": 720, "employment_status": "self-employed"},
    {"debt_to_income_ratio": 50, "credit_score": 680, "employment_status": "employed"},
    {"debt_to_income_ratio": 70, "credit_score": 600, "employment_status": "unemployed"}
]

# Function to evaluate facts
def evaluate_facts(user_id):
    try:
        # Randomly select a set of facts for each user
        facts = random.choice(FACTS_LIST)
        
        # Prepare the payload
        payload = {
            "context": "finance",
            "facts": facts
        }
        
        # Send the request
        start_time = time.time()
        response = requests.post(API_URL, json=payload)
        end_time = time.time()
        
        # Log the result
        if response.status_code == 200:
            print(f"User {user_id}: Success! Response: {response.json()}, Time: {end_time - start_time:.2f}s")
        else:
            print(f"User {user_id}: Failed! Status Code: {response.status_code}, Error: {response.text}")
    
    except Exception as e:
        print(f"User {user_id}: Exception occurred - {str(e)}")

# Main function to simulate concurrent users
def main():
    start_time = time.time()
    
    # Use ThreadPoolExecutor to simulate concurrent users
    with concurrent.futures.ThreadPoolExecutor(max_workers=NUM_USERS) as executor:
        # Submit tasks for each user
        futures = [executor.submit(evaluate_facts, user_id) for user_id in range(NUM_USERS)]
        
        # Wait for all tasks to complete
        concurrent.futures.wait(futures)
    
    end_time = time.time()
    print(f"\nTotal time taken: {end_time - start_time:.2f}s")

if __name__ == "__main__":
    main()
