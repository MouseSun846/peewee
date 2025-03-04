conn = dmPython.connect(user="SYSDBA", host="10.0.102.67", port="30236", password="Leinao@123")


set PEEWEE_DMSQL_USER=SYSDBA
set PEEWEE_DMSQL_HOST=10.0.102.67
set PEEWEE_DMSQL_PORT=30236
set PEEWEE_DMSQL_PASSWORD=Leinao@123
set PEEWEE_TEST_BACKEND=dmsql

pytest tests\pool.py::TestPooledDatabaseIntegration
pytest tests\pool.py::TestPooledDatabaseIntegration::test_pool_with_models