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

        self.wfile.write(bytes(json.dumps(content["content"]), "UTF-8"))

    def create_network_policy(self, body):
        content = dict()
        content["content"] = list()
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
                    "policyTypes": body.get("types", ["Ingress", "Egress"]),
                }
            }

            try:
                api_response = api_instance.create_namespaced_network_policy(workload["namespace"], policy)
            except ApiException as e:
                response_body = json.loads(e.body)
                # print("Exception when calling NetworkingV1Api->create_namespaced_network_policy: \n", e)
                content["code"] = response_body["code"]
                content["type"] = "application/json"
                content["content"].append({"namespace": workload["namespace"], "message": response_body["message"]})
            except Exception as e:
                # print("Unknown error: ", e)
                content["code"] = 500
                content["type"] = "text/plain"
                content["content"].append({"namespace": workload["namespace"], "message": "unknown error"})
            else:
                # print(api_response)
                content["code"] = 201
                content["type"] = "application/json"
                content["content"].append({"namespace": workload["namespace"], "message": "network policy successfully created"})
        
        self.respond(content["code"], content)

    def healthz(self):
        """Responds with the health status of the application"""
        content = dict()
        content["code"] = 200
        content["type"] = "text/plain"
        content["content"] = "ok"
        self.respond(content["code"], content)
    
    def get_deployment_replicas(self):

        content = dict()
        content["type"] = "application/json"
        content["content"] = dict()
        content["content"]["Deployments"] = dict()
        api_client = client.ApiClient()
        api_instance = client.AppsV1Api(api_client)

        try:
            deployments = api_instance.list_deployment_for_all_namespaces().items
        except ApiException as e:
            content["code"] = 500
            content["type"] = "application/json"
            content["content"] = {"error": f"something went wrong. {json.loads(e.body)}"}
        else:
            content["code"] = 200
            content["type"] = "application/json"
            for deployment in deployments:
                content["content"]["Deployments"][deployment.metadata.name] = dict()
                content["content"]["Deployments"][deployment.metadata.name]["Name"] = deployment.metadata.name
                content["content"]["Deployments"][deployment.metadata.name]["Namespace"] = deployment.metadata.namespace
                content["content"]["Deployments"][deployment.metadata.name]["Desired"] = deployment.spec.replicas
                content["content"]["Deployments"][deployment.metadata.name]["Available"] = deployment.status.available_replicas

        self.respond(content["code"], content) ## probably add try-except

    def liveness_check(self):
        api_client = client.ApiClient()
        content = dict()
        try:
            api_response = client.VersionApi(api_client).get_code()
            client_version = api_response.git_version
        except ApiException as e:
            response_body = json.loads(e.body)
            content["code"] = response_body["code"]
            content["type"] = "application/json"
            content["content"] = {"clusterStatus": response_body["message"]}
            # print("Cannot connect to K8s cluster, please check configuration. Message: ", e)
        else:
            content["code"] = 200
            content["type"] = "application/json"
            content["content"] = {"clusterStatus": "live"}
            # print("cluster live")

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
        print("invalid server address format")
        return

    with socketserver.TCPServer((host, int(port)), AppHandler) as httpd:
        print("Server listening on {}".format(address))
        httpd.serve_forever()
