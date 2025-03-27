import json
from typing import Any, Generator
from neo4j import GraphDatabase
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
import json_repair
import matplotlib.pyplot as plt
import networkx as nx
import io
import base64



class Neo4jCRUDTool(Tool):
    def _visualize_graph(self, session, node_label: str, properties: dict) -> Generator[str, None, None]:
        """
        Fetches nodes based on label and multiple partial property value matches.
        Generates a graph visualization as a Base64 encoded image and returns a Blob.

        :param node_label: The label of the node (e.g., "Research_Paper")
        :param properties: Dictionary of properties to match (e.g., {"title": "Attention", "year": "2017"})
        """
        try:
            if not properties:
                return "⚠ No properties provided for filtering."

            # Construct dynamic WHERE clause based on partial matches
            where_conditions = " AND ".join([f"n.{key} CONTAINS ${key}" for key in properties])

            match_node_query = f"""
            MATCH (n:{node_label})
            WHERE {where_conditions}
            RETURN n
            LIMIT 1
            """
            node_result = session.run(match_node_query, **properties).single()

            if not node_result:
                return f"⚠ No nodes found with label `{node_label}` and matching `{properties}`."

            target_node = node_result["n"]
            target_node_id = target_node.id
            target_node_name = target_node.get(next(iter(properties.keys())), f"Node {target_node_id}")

            # Fetch immediate neighbors
            cypher_query = """
            MATCH (n)-[r]-(neighbor)
            WHERE ID(n) = $node_id
            RETURN n, r, neighbor
            """
            result = session.run(cypher_query, node_id=target_node_id)

            # Create NetworkX graph
            G = nx.DiGraph()
            node_colors = {}

            G.add_node(target_node_name)
            node_colors[target_node_name] = "orange"  # Target node in orange

            for record in result:
                neighbor_node = record["neighbor"]
                relationship = record["r"].type

                # Define fallback properties for neighbors
                if "Author" in neighbor_node.labels:
                    node_name = neighbor_node.get("name", f"Author {neighbor_node.id}")
                    node_colors[node_name] = "lightgreen"  # Author nodes in green
                elif "Research_Paper" in neighbor_node.labels or "Reference_Paper" in neighbor_node.labels:
                    node_name = neighbor_node.get("title", f"Paper {neighbor_node.id}")
                    node_colors[node_name] = "skyblue"  # Papers in skyblue
                elif "Source" in neighbor_node.labels:
                    node_name = neighbor_node.get("name", f"Source {neighbor_node.id}")
                    node_colors[node_name] = "lightblue"
                elif "Topic" in neighbor_node.labels:
                    node_name = neighbor_node.get("name", f"Topic {neighbor_node.id}")
                    node_colors[node_name] = "lightcoral"
                elif "Concept" in neighbor_node.labels:
                    node_name = neighbor_node.get("name", f"Concept {neighbor_node.id}")
                    node_colors[node_name] = "lightcoral"
                else:
                    node_name = neighbor_node.get("display_name") or neighbor_node.get("name") or neighbor_node.get("title") or f"Node {neighbor_node.id}"
                    node_colors[node_name] = "gray"  # Default fallback color

                G.add_edge(target_node_name, node_name, label=relationship)

            if G.number_of_nodes() == 1:
                return f"⚠ No connections found for `{target_node_name}`."

            # Plot the graph
            plt.figure(figsize=(12, 8))
            pos = nx.spring_layout(G)
            node_color_list = [node_colors[node] for node in G.nodes()]
            
            nx.draw(G, pos, with_labels=True, node_color=node_color_list, edge_color="gray", node_size=3000, font_size=10)
            nx.draw_networkx_edge_labels(G, pos, edge_labels={(u, v): d["label"] for u, v, d in G.edges(data=True) if "label" in d})
            plt.title(f"Neo4j Graph for: {target_node_name}")

            # Save image to buffer
            buffer = io.BytesIO()
            plt.savefig(buffer, format="png", dpi=50)
            buffer.seek(0)
            image_blob = buffer.read()
            base64_str = base64.b64encode(image_blob).decode("utf-8")
            buffer.close()
            plt.close()

            # Return both base64 image and blob
            return {
                "base64": f"data:image/png;base64,{base64_str}",
                "blob": image_blob
            }

        except Exception as e:
            raise Exception(f"Error visualizing graph: {str(e)}")


    
    def _invoke(
        self, tool_parameters: dict[str, Any]
    ) -> Generator[ToolInvokeMessage, None, None]:
        """
        Executes CRUD operations in Neo4j.
        """
        uri = self.runtime.credentials["neo4j_uri"]
        user = self.runtime.credentials["neo4j_user"]
        password = self.runtime.credentials["neo4j_password"]

        operation = tool_parameters["operation"]
        node_label = tool_parameters.get("node_label", "")  # start node label
        properties_str = tool_parameters.get("properties", "{}")  # Get JSON string
        query = tool_parameters.get("query", "")
        end_node_label = tool_parameters.get("end_node_label", "")
        end_node_properties_str = tool_parameters.get("end_node_properties", "{}")
        relationship_type = tool_parameters.get("relationship_type", "")
        update_parameter_str = tool_parameters.get("update_parameter", "{}")
        # print(f"Operation: {operation}, Node Label: {node_label}, Properties: {properties_str}, Query: {query}")
        # Convert properties and update_parameter from string to dictionary safely
        try:
            properties = (
                json_repair.loads(properties_str) if properties_str.strip() else {}
            )
            update_parameter = (
                json_repair.loads(update_parameter_str)
                if update_parameter_str.strip() and operation == "update"
                else {}
            )
            if operation == "update_relationship":
                update_parameter =update_parameter_str
            end_node_properties = (
                json_repair.loads(end_node_properties_str)
                if end_node_properties_str.strip()
                else {}
            )
        except json.JSONDecodeError:
            raise Exception("Error: Invalid JSON format in properties or update_parameter.")
        
        # print(f"Properties: {properties}, Update Parameter: {update_parameter}")
        
        driver = GraphDatabase.driver(uri, auth=(user, password))

        try:
            with driver.session() as session:
                if query:
                    result = session.run(query)
                    records = [record.data() for record in result]
                    response_data = (
                        {"results": records} if records else {"message": "No results found"}
                    )

                    yield self.create_text_message(
                        f" Advance Query : {query}`\nResults: {json.dumps(response_data, indent=4)}"
                    )
                    yield self.create_json_message(response_data)
                    return

                cypher_query = ""
                if operation == "visualize_graph":
                    visual = self._visualize_graph(session, node_label, properties) 
                    if isinstance(visual, str):
                        yield self.create_text_message(visual)
                        return
                    else:
                        yield  self.create_text_message(f"![Graph Image]({visual['base64']})")
                        yield self.create_json_message({"base64": f"{visual['base64']}"})
                        yield self.create_blob_message(visual["blob"], meta={"mime_type": "image/png"})
                        
                        return
                elif operation == "create":
                    cypher_query = f"CREATE (n:{node_label} $properties) RETURN n"
                elif operation == "read":
                    cypher_query = f"MATCH (n:{node_label}) RETURN n"
                elif operation == "update":
                    if not properties:
                        raise Exception("Error: Matching properties required for updates.")
                    if not update_parameter and operation == 'update':
                        raise Exception("Error: `update_parameter` is required for updates.")
                    match_conditions = " AND ".join(
                        [f"n.{key} = $properties.{key}" for key in properties]
                    )
                    update_str = ", ".join(
                        [f"n.{key} = $update_parameter.{key}" for key in update_parameter]
                    )
                    cypher_query = f"MATCH (n:{node_label}) WHERE {match_conditions} SET {update_str} RETURN n"
                elif operation == "delete":
                    if properties:
                        match_conditions = " AND ".join(
                            [f"n.{key} = $properties.{key}" for key in properties]
                        )
                        cypher_query = f"MATCH (n:{node_label}) WHERE {match_conditions} DETACH DELETE n RETURN 'Node and relationships deleted'"
                    elif node_label:
                        cypher_query = f"MATCH (n:{node_label}) DETACH DELETE n RETURN 'Nodes and relationships deleted'"
                elif operation == "delete_all":
                    cypher_query = "MATCH (n) DETACH DELETE n RETURN 'All nodes and relationships deleted'"
                elif operation == "create_relationship":
                    if not node_label or not end_node_label or not relationship_type:
                        raise Exception("Error: start node label, end node label, and relationship_type are required.")
                    if not properties or not end_node_properties:
                        raise Exception("Error: Both start and end node properties are required.")
                    
                    cypher_query = f"""
                        MATCH (a:{node_label} {{name: '{properties.get('name')}'}}),
                              (b:{end_node_label} {{name: '{end_node_properties.get('name')}'}})
                        MERGE (a)-[r:{relationship_type}]->(b)
                        RETURN type(r) AS relationship
                    """
                    # print("Generated Query:", cypher_query)
                elif operation == "createNodesWithRelationship":
                    if not node_label or not end_node_label or not relationship_type:
                        raise Exception("Error: start node label, end node label, and relationship_type are required.")
                    
                    cypher_query = f"""
                        MERGE (a:{node_label} {{ {', '.join([f'{key}: $properties.{key}' for key in properties])} }})
                        MERGE (b:{end_node_label} {{ {', '.join([f'{key}: $end_properties.{key}' for key in end_node_properties])} }})
                        MERGE (a)-[r:{relationship_type}]->(b)
                        RETURN a, b, type(r) AS relationship
                    """
                    # print("Generated Query:", cypher_query)
                elif operation == "update_relationship":
                    if not node_label or not end_node_label or not relationship_type:
                        raise Exception("Error: Start node label, end node label, and relationship_type are required.")
                    if not properties or not end_node_properties:
                        raise Exception("Error: Both start and end node properties are required.")
                    
                    start_node_match = " AND ".join(
                        [f"a.{key} = '{value}'" for key, value in properties.items()]
                    )
                    end_node_match = " AND ".join(
                        [f"b.{key} = '{value}'" for key, value in end_node_properties.items()]
                    )
                    
                    cypher_query = f"""
                        MATCH (a:{node_label})-[r:{relationship_type}]->(b:{end_node_label})
                        WHERE {start_node_match} AND {end_node_match}
                    """
                    
                    if isinstance(update_parameter, str) and update_parameter.strip():
                        cypher_query += f" CREATE (a)-[new_r:{update_parameter}]->(b) DELETE r RETURN a, new_r, b"
                    else:
                        cypher_query += " RETURN a, r, b"
                elif operation == "delete_relationship_between_nodes":
                    if not node_label or not end_node_label or not relationship_type:
                        raise Exception("Error: Start node label, end node label, and relationship_type are required.")
                    if not properties or not end_node_properties:
                        raise Exception("Error: Both start and end node properties are required.")
                    
                    start_node_match = " AND ".join(
                        [f"a.{key} = '{value}'" for key, value in properties.items()]
                    )
                    end_node_match = " AND ".join(
                        [f"b.{key} = '{value}'" for key, value in end_node_properties.items()]
                    )
                    
                    cypher_query = f"""
                        MATCH (a:{node_label})-[r:{relationship_type}]->(b:{end_node_label})
                        WHERE {start_node_match} AND {end_node_match}
                        DELETE r
                        RETURN COUNT(r) as deleted_count
                    """
                
                if not cypher_query.strip():
                    raise Exception("Error: Generated Cypher query is empty.")
                
                result = session.run(cypher_query, {
                    "properties": properties,
                    "update_parameter": update_parameter,
                    "end_properties": end_node_properties,
                    "relationship_type": relationship_type,
                })
                records = [record.data() for record in result]
                response_data = (
                    {"results": records} if records else {"message": "No results found"}
                )

                yield self.create_text_message(
                    f"Operation `{operation.upper()}` executed on `{node_label if node_label else 'all nodes'}`\nResults: {json.dumps(response_data, indent=4)}"
                )
                yield self.create_json_message(response_data)

        except Exception as e:
            raise Exception(f"Error: {str(e)}")
        finally:
            driver.close()
