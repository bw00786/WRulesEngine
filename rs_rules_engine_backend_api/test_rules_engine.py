import pytest
import requests
import json

BASE_URL = "http://localhost:8000"

# Sample facts for rule evaluation
sample_facts = {
    "age": 55,
    "savings": 200000,
    "contribution": 15000
}

@pytest.fixture(scope="module")
def upload_test_rules():
    """Uploads an Excel file containing rules before running the evaluation tests."""
    with open("secureact2.xlsx", "rb") as file:
        response = requests.post(f"{BASE_URL}/rules/upload/", files={"file": file})
    
    assert response.status_code == 200, "Failed to upload rules"
    print("✅ Rules uploaded successfully")
    return response.json()

def test_evaluate_rules(upload_test_rules):
    """Tests the rule evaluation endpoint with predefined facts."""
    response = requests.post(
        f"{BASE_URL}/evaluate/",
        json={"facts": sample_facts, "use_llm": False}  # Traditional rule evaluation
    )
    
    assert response.status_code == 200, "Rule evaluation failed"
    
    data = response.json()
    assert "actions" in data, "Response does not contain actions"
    
    print("✅ Rule evaluation passed!")
    print(json.dumps(data, indent=2))

if __name__ == "__main__":
    pytest.main(["-v", "test_rules_engine.py"])

