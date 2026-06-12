import requests, json, os
from dotenv import load_dotenv
load_dotenv()
api_key = os.getenv("BUFFER_API_KEY")
q = """
query {
  __type(name: "InstagramPostMetadataInput") {
    name
    inputFields {
      name
      type {
        name
        kind
      }
    }
  }
}
"""
res = requests.post("https://api.buffer.com", headers={"Authorization": f"Bearer {api_key}"}, json={"query": q})
print(json.dumps(res.json(), indent=2))
