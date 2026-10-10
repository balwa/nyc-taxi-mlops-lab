"""S7: the MCP server's database user. query_zone_stats must not run as labadmin: create a user that can
read the marts schema and nothing else (decision: database role scope), with the RedshiftData resource.
The MCP server connects as it through the Data API's --db-user path (MCP_DB_USER, default lab_ro), so it
needs no password. Remember the mart is refreshed: grants must survive that.
"""
