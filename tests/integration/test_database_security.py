import os

from sqlalchemy import create_engine, text


def test_all_application_tables_have_rls_and_schema_is_not_public() -> None:
    engine = create_engine(os.environ["SCOUT_DATABASE_URL"])
    with engine.connect() as connection:
        table_count, rls_count = connection.execute(
            text(
                """
                select count(*), count(*) filter (where c.relrowsecurity)
                from pg_class c
                join pg_namespace n on n.oid = c.relnamespace
                where n.nspname = 'scout' and c.relkind = 'r'
                """
            )
        ).one()
        public_acl_count = connection.execute(
            text(
                """
                select count(*)
                from pg_namespace n
                cross join lateral aclexplode(n.nspacl) acl
                where n.nspname = 'scout' and acl.grantee = 0
                """
            )
        ).scalar_one()
    engine.dispose()

    assert table_count == 41
    assert rls_count == table_count
    assert public_acl_count == 0
