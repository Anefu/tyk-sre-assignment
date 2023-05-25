import socketserver
import json

from kubernetes import client
from kubernetes.client.rest import ApiException
from http.server import BaseHTTPRequestHandler


class AppHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        """Catch all incoming GET requests"""
        match self.path:
            case "/healthz":
                self.healthz()
            case "/deployments/all/replicas":
                self.get_deployment_replicas()
            case "/cluster/health":
                self.liveness_check()
            case _:
                self.send_error(404)

    def do_POST(self):
        """Catch all incoming POST requests"""
        content_len = int(self.headers.get('Content-Length'))
        body = json.loads(self.rfile.read(content_len))

        match self.path:
            case "/create/network-policy":
                self.create_network_policy(body)
            case _:
                self.send_error(404)

    def respond(self, status: int, content: dict):
        """Writes content and status code to the response socket"""
        self.send_response(status)
        self.send_header('Content-Type', content["type"])
        self.end_headers()

        self.wfile.write(bytes(json.dumps(content["body"]), "UTF-8"))

    def create_network_policy(self, body):
        """
        body:
            {
                policy: {
                    name: policy name
                    types: [policy types]
                    workloads: [
                        {
                            namespace: first workload namespace
                            labels: {
                                label-name: label-value
                            }
                        },
                        {
                            namespace: second workload namespace
                            labels: {
                                label-name: label-value
                            }
                        }
                    ]
                }
            }
        """
        DEFAULT_POLICY_TYPES = ["Ingress", "Egress"]
        content = {
            "code": 0,
            "type": "application/json",
            "body": []
        }

        api_client = client.ApiClient()
        api_instance = client.NetworkingV1Api(api_client)

        for workload in body["policy"]["workloads"]:
            policy = {
                "apiVersion": "networking.k8s.io/v1",
                "kind": "NetworkPolicy",
                "metadata": {
                    "name": body["policy"]["name"],
                    "namespace": workload["namespace"]
                },
                "spec": {
                    "podSelector": {
                        "matchLabels": workload["labels"]
                    },
                    "policyTypes": body.get("types", DEFAULT_POLICY_TYPES),
                }
            }

            try:
                api_response = api_instance.create_namespaced_network_policy(workload["namespace"], policy)
            except ApiException as e:
                response_body = json.loads(e.body)
                content["code"] = response_body["code"]
                content["body"].append({"namespace": workload["namespace"], "message": response_body["message"]})
            except Exception as e:
                content["code"] = 500
                content["body"].append({"namespace": workload["namespace"], "message": "unknown error"})
            else:
                content["code"] = 201
                content["body"].append({"namespace": workload["namespace"], "message": "network policy successfully created"})

        self.respond(content["code"], content)

    def healthz(self):
        """Responds with the health status of the application"""
        content = {
            "code": 200,
            "type": "text/plain",
            "body": "ok"
        }
        self.respond(content["code"], content)

    def get_deployment_replicas(self):
        content = {
            "code": 0,
            "type": "application/json",
            "body": {
                "Deployments": {}
            }
        }
        api_client = client.ApiClient()
        api_instance = client.AppsV1Api(api_client)

        try:
            deployments = api_instance.list_deployment_for_all_namespaces().items
        except ApiException as e:
            content["code"] = 500
            content["body"] = {"error": f"something went wrong. {json.loads(e.body)}"}
        else:
            content["code"] = 200
            for deployment in deployments:
                deployment_info = {
                    "Name": deployment.metadata.name,
                    "Namespace": deployment.metadata.namespace,
                    "Desired": deployment.spec.replicas,
                    "Available": deployment.status.available_replicas or 0
                }
                content["body"]["Deployments"][f"{deployment.metadata.name}_{deployment.metadata.namespace}"] = deployment_info

        self.respond(content["code"], content)

    def liveness_check(self):
        api_client = client.ApiClient()
        content = {
            "code": 0,
            "type": "application/json",
            "body": {}
        }
        try:
            api_response = client.VersionApi(api_client).get_code()
            client_version = api_response.git_version
        except ApiException as e:
            response_body = json.loads(e.body)
            content["code"] = response_body["code"]
            content["body"] = {"clusterStatus": response_body["message"]}
        else:
            content["code"] = 200
            content["body"] = {"clusterStatus": "live"}

        self.respond(content["code"], content)

def get_kubernetes_version(api_client: client.ApiClient) -> str:
    """
    Returns a string GitVersion of the Kubernetes server defined by the api_client.

    If it can't connect an underlying exception will be thrown.
    """
    version = client.VersionApi(api_client).get_code()
    return version.git_version

def start_server(address):
    """
    Launches an HTTP server with handlers defined by AppHandler class and blocks until it's terminated.

    Expects an address in the format of `host:port` to bind to.

    Throws an underlying exception in case of error.
    """
    try:
        host, port = address.split(":")
    except ValueError:
        print("Invalid server address format")
        return

    with socketserver.TCPServer((host, int(port)), AppHandler) as httpd:
        print(f"Server listening on {address}")
        httpd.serve_forever()
