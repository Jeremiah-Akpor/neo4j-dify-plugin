import json
from typing import Any, Generator
from neo4j import GraphDatabase
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
import json_repair


class Neo4jCRUDTool(Tool):
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
        update_properties_str = tool_parameters.get(
            "update_properties", "{}"
        )  # Get JSON string for updates
        query = tool_parameters.get("query", "")
        end_node_label = tool_parameters.get("end_node_label", "")
        end_node_properties_str = tool_parameters.get("end_node_properties", "{}")
        relationship_type = tool_parameters.get("relationship_type", "")

        # Convert properties and update_properties from string to dictionary safely
        try:
            properties = (
                json_repair.loads(properties_str) if properties_str.strip() else {}
            )
        except json.JSONDecodeError:
            raise Exception("Error: Invalid properties JSON string.")

        try:
            update_properties = (
                json_repair.loads(update_properties_str)
                if update_properties_str.strip()
                else {}
            )
        except json.JSONDecodeError:
            raise Exception("Error: Invalid update_properties JSON string.")

        try:
            end_node_properties = (
                json_repair.loads(end_node_properties_str)
                if end_node_properties_str.strip()
                else {}
            )
        except json.JSONDecodeError:
            raise Exception("Error: Invalid end_node_properties JSON string.")
        
        driver = GraphDatabase.driver(uri, auth=(user, password))

        try:
            with driver.session() as session:
                if query:
                    result = session.run(query, {**properties, **update_properties})
                    records = [record.data() for record in result]
                    yield self.create_json_message(records)
                    return

                cypher_query = ""
                if operation == "create":
                    cypher_query = f"CREATE (n:{node_label} $properties) RETURN n"
                elif operation == "read":
                    cypher_query = f"MATCH (n:{node_label}) RETURN n"
                elif operation == "update":
                    if not properties:
                        raise Exception(
                            "Error: Matching properties required for updates."
                        )
                    if not update_properties:
                        raise Exception(
                            "Error: `update_properties` is required for updates."
                        )
                    match_conditions = " AND ".join(
                        [f"n.{key} = $properties.{key}" for key in properties]
                    )
                    update_str = ", ".join(
                        [
                            f"n.{key} = $update_properties.{key}"
                            for key in update_properties
                        ]
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
                    print("Generated Query:", cypher_query)
                elif operation == "createNodesWithRelationship":
                    if not node_label or not end_node_label or not relationship_type:
                        raise Exception("Error: start node label, end node label, and relationship_type are required.")
                    
                    cypher_query = f"""
                        MERGE (a:{node_label} {{ {', '.join([f'{key}: $start_properties.{key}' for key in properties])} }})
                        MERGE (b:{end_node_label} {{ {', '.join([f'{key}: $end_properties.{key}' for key in end_node_properties])} }})
                        MERGE (a)-[r:{relationship_type}]->(b)
                        RETURN a, b, type(r) AS relationship
                    """
                    print("Generated Query:", cypher_query)
                
                if not cypher_query.strip():
                    raise Exception("Error: Generated Cypher query is empty.")
                
                result = session.run(cypher_query, {
                    "start_properties": properties,
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
