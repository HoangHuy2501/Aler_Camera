from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from config import database_url


def connect_pool() -> ConnectionPool:
    return ConnectionPool(database_url(), min_size=1, max_size=10,
                          kwargs={"row_factory": dict_row}, open=False)
