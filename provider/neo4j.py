from typing import Any
from neo4j import GraphDatabase
from dify_plugin import ToolProvider
from dify_plugin.errors.tool import ToolProviderCredentialValidationError
from tools.neo4j import Neo4jCRUDTool

class Neo4jProvider(ToolProvider):
    def _validate_credentials(self, credentials: dict[str, Any]) -> None:
        """
        Validate Neo4j credentials by trying to connect.
        """
        try:
            uri = credentials["neo4j_uri"]
            user = credentials["neo4j_user"]
            password = credentials["neo4j_password"]

            driver = GraphDatabase.driver(uri, auth=(user, password))
            with driver.session() as session:
                session.run("RETURN 1")
        except Exception as e:
            raise ToolProviderCredentialValidationError(str(e))
