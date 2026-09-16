import argparse
import asyncio

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import ExperimentEvent, ExperimentRun, utc_now
from app.runner import ExperimentExecutionError, execute_experiment


def append_events(database, experiment_id, events):
    last_sequence = database.scalar(
        select(func.coalesce(func.max(ExperimentEvent.sequence), 0))
        .where(ExperimentEvent.experiment_id == experiment_id)
    )

    for offset, event in enumerate(events, start=1):
        database.add(
            ExperimentEvent(
                experiment_id=experiment_id,
                sequence=last_sequence + offset,
                event_type=event.event_type,
                detail=event.detail,
                occurred_at=event.occurred_at,
            )
        )


def claim_next_experiment():
    with SessionLocal() as database:
        experiment = database.scalar(
            select(ExperimentRun)
            .where(ExperimentRun.status.in_(["queued", "running"]))
            .order_by(ExperimentRun.created_at)
            .limit(1)
        )

        if experiment is None:
            return None

        was_interrupted = experiment.status == "running"

        if experiment.attempt_count >= experiment.max_attempts:
            experiment.status = "failed"
            experiment.error_code = "MAX_ATTEMPTS_REACHED"
            experiment.error_detail = "Worker exhausted all retry attempts"
            experiment.completed_at = utc_now()
            database.commit()
            return None

        experiment.status = "running"
        experiment.attempt_count += 1
        experiment.started_at = utc_now()

        if was_interrupted:
            database.add(
                ExperimentEvent(
                    experiment_id=experiment.id,
                    sequence=len(experiment.events) + 1,
                    event_type="worker_recovered",
                    detail="Recovered an experiment interrupted mid-job",
                )
            )

        job = {
            "id": experiment.id,
            "attempt_number": experiment.attempt_count,
            "authorization_mode": experiment.authorization_mode,
            "cutoff_seconds": experiment.cutoff_seconds,
        }

        database.commit()
        return job


async def process_experiment(job):
    try:
        outcome = await execute_experiment(
            experiment_id=job["id"],
            attempt_number=job["attempt_number"],
            authorization_mode=job["authorization_mode"],
            cutoff_seconds=job["cutoff_seconds"],
        )
    except ExperimentExecutionError as error:
        with SessionLocal() as database:
            experiment = database.get(ExperimentRun, job["id"])
            append_events(database, experiment.id, error.events)

            experiment.error_code = "EXPERIMENT_EXECUTION_ERROR"
            experiment.error_detail = str(error)

            if experiment.attempt_count < experiment.max_attempts:
                experiment.status = "queued"
            else:
                experiment.status = "failed"
                experiment.completed_at = utc_now()

            database.commit()
        return

    with SessionLocal() as database:
        experiment = database.get(ExperimentRun, job["id"])
        append_events(database, experiment.id, outcome.events)

        experiment.status = "succeeded"
        experiment.result = outcome.result
        experiment.error_code = None
        experiment.error_detail = None
        experiment.completed_at = utc_now()
        database.commit()


async def run_worker(once):
    while True:
        job = claim_next_experiment()

        if job is None:
            if once:
                print("No queued experiments")
                return

            await asyncio.sleep(2)
            continue

        print(f"Processing experiment {job['id']}")
        await process_experiment(job)

        if once:
            return


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process one experiment and exit",
    )
    arguments = parser.parse_args()
    asyncio.run(run_worker(arguments.once))