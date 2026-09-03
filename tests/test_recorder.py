from __future__ import annotations

from rpa_core.recorder import RecorderManager, parameterize_events


def test_parameterize_events_uses_readable_input_names_and_deduplicates():
    events = [
        {"type": "fill", "target": {"label": "Data inicial"}, "value": "", "meta": {"recorded_input": True, "label": "Data inicial"}},
        {"type": "fill", "target": {"label": "Data inicial"}, "value": "", "meta": {"recorded_input": True, "label": "Data inicial"}},
        {"type": "fill", "target": {"label": "Modelo"}, "value": "", "meta": {"recorded_input": True, "label": "Modelo"}},
        {"type": "click", "target": {"role": "button", "name": "Filtrar"}},
    ]

    steps, inputs = parameterize_events(events)

    assert steps == [
        {"type": "fill", "target": {"label": "Data inicial"}, "value": "{{data_inicial}}"},
        {"type": "fill", "target": {"label": "Modelo"}, "value": "{{modelo}}"},
        {"type": "click", "target": {"role": "button", "name": "Filtrar"}},
    ]
    assert inputs == {"data_inicial": "", "modelo": ""}


def test_parameterize_events_keeps_password_as_secret_reference():
    events = [
        {
            "type": "secret_fill",
            "target": {"label": "Senha"},
            "secret": "portal.password",
            "meta": {"sensitive": True, "label": "Senha"},
        },
    ]

    steps, inputs = parameterize_events(events)

    assert steps == [{"type": "secret_fill", "target": {"label": "Senha"}, "secret": "portal.password"}]
    assert inputs == {}


def test_recorder_manager_removes_finished_session(monkeypatch):
    manager = RecorderManager()

    def fake_run_session(session):
        session.status = "finished"

    monkeypatch.setattr(manager, "_run_session", fake_run_session)
    session = manager.start("example.com")
    session.thread.join(timeout=5)

    assert manager.get(session.id) is session
    assert manager.stop(session.id) is session
    assert manager.get(session.id) is None
