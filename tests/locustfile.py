from locust import HttpUser, task, between, events
import random

class SellerUser(HttpUser):
    wait_time = between(0.1, 0.5)
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.username = "root"
        self.charge_sales_made = 0
    
    def on_start(self):
        # Assign alternating usernames to distribute load
        self.username = "root" if self.environment.runner.user_count % 2 == 0 else "root1"
        self.password = self.username
        
        # Get auth token
        response = self.client.post("/drf/auth-token/", 
            json={"username": self.username, "password": self.password})
            
        if response.status_code != 200:
            raise Exception(f"Failed to authenticate {self.username}")
        
        token = response.json()["token"]
        self.client.headers.update({
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        })

        amount = random.randint(1000000, 2000000)
        response = self.client.post("/api/charge/credit-requests", 
            json={"amount": amount})
        
        if response.status_code == 200:
            request_id = response.json()["id"]
            self.client.post(f"/api/charge/credit-requests/{request_id}/approve")

    @task
    def charge_sale(self):
        # Stop if we've made 10 sales (with 100 users this gives us 1000 total)
        if self.charge_sales_made >= 10:
            return

        phones_response = self.client.get("/api/charge/phone-numbers")
        if phones_response.status_code == 200:
            phones = phones_response.json()
            if phones:
                phone = random.choice(phones)
                amount = random.randint(1000, 5000)
                
                response = self.client.post("/api/charge/charge-sales", 
                    json={
                        "amount": amount,
                        "phone_number_id": phone["id"]
                    },
                    verify=False)
                
                if response.status_code == 200:
                    self.charge_sales_made += 1

@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Validate transactions by calling the validate endpoint"""
    if environment.stats.total.num_requests == 0:
        return

    print("\n=== Test Summary ===")
    try:
        # Create a test user instance to get authenticated client
        test_user = environment.runner.user_classes[0](environment)
        
        # Authenticate first
        credentials = {
            "username": "root",
            "password": "root"
        }
        auth_response = test_user.client.post("/drf/auth-token/", json=credentials)
        
        if auth_response.status_code != 200:
            print(f"Failed to authenticate: {auth_response.text}")
            return
            
        # Set authorization header
        token = auth_response.json()["token"]
        test_user.client.headers = {"Authorization": f"Bearer {token}"}
        
        # Make the validation request
        response = test_user.client.get("/api/charge/validate")
        
        if response.status_code == 200:
            results = response.json()
            print("Validation Results:")
            print(f"Total approved credits: {results['total_approved_credits']}")
            print(f"Current user credits: {results['current_user_credits']}")
            print(f"Total spent credits: {results['total_spent_credits']}")
            print(f"Total charge sales: {results['total_charge_sales']}")
            print(f"Consistency check: {'PASSED' if results['is_consistent'] else 'FAILED'}")
            print(f"Details: {results['details']}")
    except Exception as e:
        print(f"Failed to get validation results: {e}")