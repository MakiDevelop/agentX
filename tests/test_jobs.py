from agentx.jobs import PromptJobQueue
from agentx.cli import cancel_jobs


def test_prompt_job_queue_cancel_pending_by_id():
    jobs = PromptJobQueue()
    first = jobs.submit("first")
    second = jobs.submit("second")

    cancelled = jobs.cancel_pending(second.id)

    assert [job.id for job in cancelled] == [second.id]
    assert [job.id for job in jobs.pending()] == [first.id]


def test_prompt_job_queue_tracks_current_job():
    jobs = PromptJobQueue()
    submitted = jobs.submit("task")

    current = jobs.get()

    assert current == submitted
    assert jobs.current == submitted

    jobs.complete_current()

    assert jobs.current is None


def test_cancel_jobs_reports_cancelled_ids():
    jobs = PromptJobQueue()
    first = jobs.submit("first")
    second = jobs.submit("second")

    result = cancel_jobs(jobs, str(first.id))

    assert result == f"cancelled queued jobs: {first.id}"
    assert [job.id for job in jobs.pending()] == [second.id]


def test_cancel_current_is_reported_as_not_supported():
    jobs = PromptJobQueue()

    assert cancel_jobs(jobs, "current") == (
        "current running job cannot be interrupted yet; queued jobs can be cancelled"
    )
