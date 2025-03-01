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
        query = tool_parameters.get("query", "")
        end_node_label = tool_parameters.get("end_node_label", "")
        end_node_properties_str = tool_parameters.get("end_node_properties", "{}")
        relationship_type = tool_parameters.get("relationship_type", "")
        update_parameter_str = tool_parameters.get("update_parameter", "{}")
        print(update_parameter_str)

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
        
        print(update_parameter)
        
        driver = GraphDatabase.driver(uri, auth=(user, password))

        try:
            with driver.session() as session:
                if query:
                    result = session.run(query, {"properties": properties, "update_parameter": update_parameter})
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

