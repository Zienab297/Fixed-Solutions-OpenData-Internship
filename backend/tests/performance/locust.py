import random
from locust import HttpUser, task, between

DOMAIN_ID = "bfcde845-1597-424d-8ee2-ab61d91f514c"  

ACCESS_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJzeXN0ZW0tYWRtaW4tMDA5IiwiZW1haWwiOiJhZG1pbkBleGFtcGxlLmNvbSIsImV4cCI6MTc4MjY2NDg1N30.wWwbjBXRdi5Suy-XD2dRb3vQoxjppbwEHO8b_los1ss"


class CVPlatformLoadTester(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        """This runs once when each simulated user starts"""
        self.client.headers = {
            "Authorization": f"Bearer {ACCESS_TOKEN}",  
            "Content-Type": "application/json"
        }

    @task(1)
    def query_cv_screening_graph(self):
        """Now sending authorized queries to the screening graph"""
        cv_related_queries = [
            "Does the applicant have experience in langgraph?",
            "Does the applicant know LangGraph?"
        ]

        self.client.post("/api/v1/query", json={
            "query": random.choice(cv_related_queries),
            "domain_ids": [DOMAIN_ID], 
            "top_k": 5
        })