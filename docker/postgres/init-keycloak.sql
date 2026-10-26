-- Runs once, when the Postgres volume is first created. Keycloak keeps its
-- own data in a separate database on the same server.
CREATE DATABASE keycloak;
