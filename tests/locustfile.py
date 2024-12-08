from datetime import datetime
from locust import HttpUser, task, between
import json
import random

class TBDLUser(HttpUser):
    wait_time = between(1, 2)
    test_user = {
        "username": "root",
        "password": "root"
    }
    
    def on_start(self):
        """Get authentication token"""
        # Get token from DRF token endpoint
        response = self.client.post("/drf/auth-token/", json=self.test_user)
        if response.status_code != 200:
            raise Exception("Failed to get auth token")
        
        token = response.json()["token"]
        
        # Setup authorization header for all requests
        self.client.headers.update({
            "Authorization": f"Bearer {token}"
        })

    @task(3)
    def list_phone_numbers(self):
        self.client.get("/api/charge/phone-numbers")

    @task(2)
    def get_phone_number(self):
        # Assuming phone IDs range from 1 to 10
        phone_id = random.randint(1, 10)
        self.client.get(f"/api/charge/phone-numbers/{phone_id}")

    @task(2)
    def list_credit_requests(self):
        self.client.get("/api/charge/credit-requests")

    @task(1)
    def create_credit_request(self):
        payload = {
            "amount": random.randint(10, 100)
        }
        response = self.client.post("/api/charge/credit-requests", json=payload)
        if response.status_code == 200:
            request_id = response.json()["id"]
            # Approve the created credit request
            self.client.post(f"/api/charge/credit-requests/{request_id}/approve")

    @task(2)
    def list_charge_sales(self):
        self.client.get("/api/charge/charge-sales")

    @task(1)
    def create_charge_sale(self):
        payload = {
            "amount": random.randint(1, 50),
            "phone_number_id": random.randint(1, 10)
        }
        self.client.post("/api/charge/charge-sales", json=payload)

class ChargeSaleUser(TBDLUser):
    """User focused on charge sale operations"""
    wait_time = between(2, 5)

    @task(3)
    def charge_workflow(self):
        # Get available phone numbers
        phones_response = self.client.get("/api/charge/phone-numbers")
        if phones_response.status_code != 200:
            return

        phones = phones_response.json()
        if not phones:
            return

        # Create and approve a credit request
        credit_amount = random.randint(1000000, 2000000)
        credit_response = self.client.post("/api/charge/credit-requests", 
            json={"amount": credit_amount})
        
        if credit_response.status_code == 200:
            request_id = credit_response.json()["id"]
            self.client.post(f"/api/charge/credit-requests/{request_id}/approve")

            # Create a charge sale
            phone = random.choice(phones)
            charge_amount = random.randint(10, credit_amount)
            self.client.post("/api/charge/charge-sales", 
                json={
                    "amount": charge_amount,
                    "phone_number_id": phone["id"]
                })

class CreditRequestUser(TBDLUser):
    """User focused on credit operations"""
    wait_time = between(3, 7)

    @task
    def credit_workflow(self):
        # List existing requests
        self.client.get("/api/charge/credit-requests")
        
        # Create new request
        amount = random.randint(100, 500)
        response = self.client.post("/api/charge/credit-requests", 
            json={"amount": amount})
        
        if response.status_code == 200:
            request_id = response.json()["id"]
            # Wait a bit before approving
            self.client.post(f"/api/charge/credit-requests/{request_id}/approve")