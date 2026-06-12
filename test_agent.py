import sys
import logging
from src.agent import AutonomousAgent

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

def run_test():
    print("Starting Autonomous Agent test cycle...")
    agent = AutonomousAgent()
    agent.run_once()
    
    print("\nChecking scheduled posts buffer:")
    posts = agent.db.get_scheduled_posts()
    for post in posts:
        print(f" - Package: {post['package_id']}, Status: {post['status']}, Scheduled For: {post['scheduled_time']}")

if __name__ == "__main__":
    run_test()
