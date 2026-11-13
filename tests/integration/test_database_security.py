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

    assert table_count == 45
    assert rls_count == table_count
    assert public_acl_count == 0


def test_review_reversal_constraints_and_active_decision_indexes_are_valid() -> None:
    engine = create_engine(os.environ["SCOUT_DATABASE_URL"])
    with engine.connect() as connection:
        constraints = set(
            connection.execute(
                text(
                    """
                    select conname
                    from pg_constraint
                    where connamespace = 'scout'::regnamespace
                      and conname in (
                        'ck_individual_review_decisions_reversal_fields_complete',
                        'ck_opportunity_review_decisions_reversal_fields_complete'
                      )
                      and convalidated
                    """
                )
            ).scalars()
        )
        index_rows = connection.execute(
            text(
                """
                    select c.relname, i.indisvalid
                    from pg_index i
                    join pg_class c on c.oid = i.indexrelid
                    join pg_namespace n on n.oid = c.relnamespace
                    where n.nspname = 'scout'
                      and c.relname in (
                        'uq_individual_review_decisions_active_candidate',
                        'uq_opportunity_review_decisions_active_hypothesis'
                      )
                    """
            )
        ).tuples()
        indexes = {name: is_valid for name, is_valid in index_rows}
    engine.dispose()

    assert constraints == {
        "ck_individual_review_decisions_reversal_fields_complete",
        "ck_opportunity_review_decisions_reversal_fields_complete",
    }
    assert indexes == {
        "uq_individual_review_decisions_active_candidate": True,
        "uq_opportunity_review_decisions_active_hypothesis": True,
    }
