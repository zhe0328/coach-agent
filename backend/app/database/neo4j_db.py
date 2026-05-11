from neo4j import GraphDatabase
from app.config import settings


class Neo4jManager:
    _driver = None

    @classmethod
    def get_driver(cls):
        if cls._driver is None:
            cls._driver = GraphDatabase.driver(
                settings.NEO4J_BASE_URL,
                auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD),
            )
        return cls._driver

    @classmethod
    def close_driver(cls):
        if cls._driver:
            cls._driver.close()
            cls._driver = None

    @classmethod
    def get_session(cls):
        driver = cls.get_driver()
        return driver.session()
