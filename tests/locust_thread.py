import random

from locust import HttpUser
from locust import between
from locust import events
from locust import task


class ThreadedSellerUser(HttpUser):
    wait_time = between(0.1, 0.5)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.username = "root"
        self.charge_sales_made = 0

    def on_start(self):
        # Similar setup as original test but with different username prefix
        self.username = random.choice(["thread1", "thread2"])
        self.password = self.username

        # Get auth token
        response = self.client.post(
            "/drf/auth-token/",
            json={"username": self.username, "password": self.password},
        )

        if response.status_code != 200:
            raise Exception(f"Failed to authenticate {self.username}")

        token = response.json()["token"]
        self.client.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )

        # Initial credit request
        amount = random.randint(1000000, 2000000)
        response = self.client.post(
            "/api/charge/credit-requests",
            json={"amount": amount},
        )

        if response.status_code == 200:
            request_id = response.json()["id"]
            self.client.post(f"/api/charge/credit-requests/{request_id}/approve")

    @task
    def threaded_charge_sale(self):
        # Stop if we've made 10 sales
        if self.charge_sales_made >= 10:
            return

        phones_response = self.client.get("/api/charge/phone-numbers")
        if phones_response.status_code == 200:
            phones = phones_response.json()
            if phones:
                phone = random.choice(phones)
                amount = random.randint(1000, 5000)

                # Use the threaded endpoint instead of the async one
                response = self.client.post(
                    "/api/charge/charge-sales/threaded",
                    json={
                        "amount": amount,
                        "phone_number_id": phone["id"],
                    },
                    verify=False,
                )

                if response.status_code == 200:
                    self.charge_sales_made += 1


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Validate transactions by calling the validate endpoint"""
    if environment.stats.total.num_requests == 0:
        return

    print("\n=== Threaded Test Summary ===")
    try:
        test_user = environment.runner.user_classes[0](environment)

        credentials = {
            "username": "thread1",
            "password": "thread1",
        }
        auth_response = test_user.client.post("/drf/auth-token/", json=credentials)

        if auth_response.status_code != 200:
            print(f"Failed to authenticate: {auth_response.text}")
            return

        token = auth_response.json()["token"]
        test_user.client.headers = {"Authorization": f"Bearer {token}"}

        response = test_user.client.get("/api/charge/validate")

        if response.status_code == 200:
            results = response.json()
            print("Threaded Validation Results:")
            print(f"Total approved credits: {results['total_approved_credits']}")
            print(f"Current user credits: {results['current_user_credits']}")
            print(f"Total spent credits: {results['total_spent_credits']}")
            print(f"Total charge sales: {results['total_charge_sales']}")
            print(
                f"Consistency check: {'PASSED' if results['is_consistent'] else 'FAILED'}",
            )
            print(f"Details: {results['details']}")
    except Exception as e:
        print(f"Failed to get validation results: {e}")
