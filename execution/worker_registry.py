from database.models import get_connection


def register_worker(
    worker_id,
    max_accounts=20
):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO worker_registry (
            worker_id,
            worker_status,
            max_accounts,
            active_accounts,
            last_heartbeat
        )
        VALUES (
            %s,
            'online',
            %s,
            0,
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (worker_id) DO UPDATE SET
            worker_status = 'online',
            max_accounts = EXCLUDED.max_accounts,
            last_heartbeat = CURRENT_TIMESTAMP
    """, (worker_id, max_accounts))

    connection.commit()
    cursor.close()
    connection.close()


def get_best_worker():
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT worker_id
        FROM worker_registry
        WHERE worker_status = 'online'
        AND active_accounts < max_accounts
        ORDER BY active_accounts ASC
        LIMIT 1
    """)

    worker = cursor.fetchone()

    cursor.close()
    connection.close()

    if worker:
        return worker["worker_id"]

    return None


def update_worker_heartbeat(
    worker_id,
    active_accounts,
    cpu_usage,
    memory_usage
):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE worker_registry
        SET
            active_accounts = %s,
            cpu_usage = %s,
            memory_usage = %s,
            last_heartbeat = CURRENT_TIMESTAMP,
            worker_status = 'online'
        WHERE worker_id = %s
    """, (
        active_accounts,
        cpu_usage,
        memory_usage,
        worker_id
    ))

    connection.commit()
    cursor.close()
    connection.close()


def mark_worker_offline(worker_id):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE worker_registry
        SET worker_status = 'offline'
        WHERE worker_id = %s
    """, (worker_id,))

    connection.commit()
    cursor.close()
    connection.close()


def get_online_workers():
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT *
        FROM worker_registry
        WHERE worker_status = 'online'
        ORDER BY active_accounts ASC
    """)

    workers = cursor.fetchall()

    cursor.close()
    connection.close()

    return workers
