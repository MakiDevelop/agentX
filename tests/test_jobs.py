import threading

from agentx.cli import cancel_jobs, handle_keyboard_interrupt, keyboard_interrupt_should_force_exit
from agentx.jobs import PromptJobQueue


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

    assert cancel_jobs(jobs, "current") == "no running job to cancel"


def test_cancel_current_sets_cancel_event_for_running_job():
    jobs = PromptJobQueue()
    submitted = jobs.submit("running")
    jobs.get()
    cancel_event = threading.Event()

    result = cancel_jobs(jobs, "current", cancel_event)

    assert result == f"cancelling running job: {submitted.id}"
    assert cancel_event.is_set()


def test_keyboard_interrupt_cancels_running_and_queued_jobs():
    jobs = PromptJobQueue()
    running = jobs.submit("running")
    queued = jobs.submit("queued")
    jobs.get()
    cancel_event = threading.Event()

    result = handle_keyboard_interrupt(jobs, cancel_event)

    assert result == f"cancelling running job: {running.id}; cancelled queued jobs: {queued.id}"
    assert cancel_event.is_set()
    assert jobs.pending() == []


def test_keyboard_interrupt_cancels_queued_jobs_before_exit():
    jobs = PromptJobQueue()
    first = jobs.submit("first")
    second = jobs.submit("second")

    result = handle_keyboard_interrupt(jobs, threading.Event())

    assert result == f"cancelled queued jobs: {first.id}, {second.id}"
    assert jobs.pending() == []


def test_keyboard_interrupt_exits_when_idle():
    jobs = PromptJobQueue()

    assert handle_keyboard_interrupt(jobs, threading.Event()) is None


def test_keyboard_interrupt_force_exit_after_cancel_requested():
    jobs = PromptJobQueue()
    jobs.submit("running")
    jobs.get()
    cancel_event = threading.Event()

    assert keyboard_interrupt_should_force_exit(jobs, cancel_event) is False

    first = handle_keyboard_interrupt(jobs, cancel_event)

    assert first == "cancelling running job: 1"
    assert cancel_event.is_set()
    assert keyboard_interrupt_should_force_exit(jobs, cancel_event) is True
