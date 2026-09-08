-- Runs once, on first container init, to also provision the test database
-- used by the pytest suite (TEST_DATABASE_URL), separate from the dev DB.
CREATE DATABASE lol_analytics_test;
