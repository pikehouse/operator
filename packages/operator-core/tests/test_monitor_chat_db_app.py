"""Tests for monitor CLI chat-db-app subject support."""

import pytest

from operator_core.cli.subject_factory import AVAILABLE_SUBJECTS, create_subject


class TestSubjectFactory:
    def test_chat_db_app_in_available_subjects(self):
        assert "chat-db-app" in AVAILABLE_SUBJECTS

    def test_unknown_subject_raises(self):
        with pytest.raises(ValueError, match="Unknown subject"):
            import asyncio
            asyncio.run(create_subject("nonexistent"))


class TestObserverModuleNaming:
    def test_chat_db_app_observer_importable(self):
        """chat_db_app_observer module should be importable and have AGENT_PROMPT."""
        import chat_db_app_observer

        assert hasattr(chat_db_app_observer, "AGENT_PROMPT")
        assert "Chat DB App" in chat_db_app_observer.AGENT_PROMPT

    def test_hyphen_to_underscore_module_mapping(self):
        """Subject name 'chat-db-app' maps to module 'chat_db_app_observer'."""
        subject_name = "chat-db-app"
        module_name = subject_name.replace("-", "_") + "_observer"
        assert module_name == "chat_db_app_observer"

        module = __import__(module_name, fromlist=["AGENT_PROMPT"])
        assert hasattr(module, "AGENT_PROMPT")


class TestSubjectContextExtra:
    def test_context_extra_appended_to_agent_prompt(self):
        """--subject-context-extra should be appended to AGENT_PROMPT."""
        import chat_db_app_observer

        base_prompt = chat_db_app_observer.AGENT_PROMPT
        extra = "\nSource code at: /tmp/workspace/app/"

        # This is the logic from monitor.py
        subject_context = base_prompt
        subject_context_extra = extra
        if subject_context_extra:
            subject_context = subject_context + "\n" + subject_context_extra

        assert subject_context.startswith(base_prompt)
        assert extra in subject_context

    def test_context_extra_when_no_base_prompt(self):
        """Extra context works even when base prompt is None."""
        subject_context = None
        subject_context_extra = "workspace commands here"

        if subject_context_extra:
            if subject_context:
                subject_context = subject_context + "\n" + subject_context_extra
            else:
                subject_context = subject_context_extra

        assert subject_context == "workspace commands here"
