"""Tests for card-scoped 'correto_circulo' evidence, never delivery inference."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "va_api_card",
    Path(__file__).parents[1] / "custom_components/vestibulare_elshaday/api.py"
)
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)


def card(day, deadline, marker="", classes="card mr-2 va-plan-card"):
    return (f'<div class="{classes}">'
            f'<div class="va-plan-card-status">{marker}</div>'
            f'<div>Aula {day} ─ <span class="">Professor Exemplo</span>'
            f'<div class="limite-linha-va-card"><span>Atividade exemplo</span></div>'
            f'<small>até {deadline}</small></div></div>')


def item(day, deadline):
    return {"data": day, "prazo": deadline}


class CardMarkerTests(unittest.TestCase):
    def test_detect_marker_only_on_own_card(self):
        page = (
            card("10/03/2026", "12/03/2026 12:00",
                 '<i class="correto_circulo"></i>') +
            card("11/03/2026", "13/03/2026 12:00",
                 '<span class="va-card-nao-lido-inferior"></span>')
        )
        result = api.inspect_correto_circulo_by_card(
            page, [item("10/03/2026", "12/03/2026 12:00"),
                   item("11/03/2026", "13/03/2026 12:00")])
        self.assertEqual(result["estado"], "marcadores_por_cartao")
        self.assertEqual([i["correto_circulo"] for i in result["itens"]],
                         [True, False])
        self.assertNotIn("status_entrega", repr(result))

    def test_reordered_css_classes_still_parse(self):
        page = card("10/03/2026", "12/03/2026 12:00",
                    '<img src="/icons/correto_circulo.png">',
                    classes="va-plan-card card mr-2")
        result = api.inspect_correto_circulo_by_card(
            page, [item("10/03/2026", "12/03/2026 12:00")])
        self.assertTrue(result["itens"][0]["correto_circulo"])

    def test_read_marker_is_not_completion(self):
        page = card("10/03/2026", "12/03/2026 12:00",
                    '<span class="va-card-lido-inferior"></span>')
        result = api.inspect_correto_circulo_by_card(
            page, [item("10/03/2026", "12/03/2026 12:00")])
        self.assertFalse(result["itens"][0]["correto_circulo"])

    def test_outside_card_does_not_cause_false_positive(self):
        page = ('<div class="correto_circulo"></div>' +
                card("10/03/2026", "12/03/2026 12:00"))
        result = api.inspect_correto_circulo_by_card(
            page, [item("10/03/2026", "12/03/2026 12:00")])
        self.assertFalse(result["itens"][0]["correto_circulo"])

    def test_data_and_deadline_mismatch_are_indeterminate(self):
        page = card("10/03/2026", "12/03/2026 12:00",
                    '<i class="correto_circulo"></i>')
        result = api.inspect_correto_circulo_by_card(
            page, [item("10/03/2026", "13/03/2026 12:00")])
        self.assertEqual(result["estado"], "estrutura_nao_validada")
        self.assertEqual(result["itens"], [])

    def test_duplicate_identifiers_are_indeterminate(self):
        page = card("10/03/2026", "12/03/2026 12:00",
                    '<i class="correto_circulo"></i>') + card(
                    "10/03/2026", "12/03/2026 12:00")
        result = api.inspect_correto_circulo_by_card(
            page, [item("10/03/2026", "12/03/2026 12:00")]*2)
        self.assertEqual(result["estado"], "estrutura_nao_validada")
        self.assertEqual(result["itens"], [])

    def test_marker_in_plain_text_is_not_evidence(self):
        page = card("10/03/2026", "12/03/2026 12:00",
                    '<span>correto_circulo</span>')
        result = api.inspect_correto_circulo_by_card(
            page, [item("10/03/2026", "12/03/2026 12:00")])
        self.assertFalse(result["itens"][0]["correto_circulo"])

    def test_missing_card_boundary_is_indeterminate(self):
        page = '<div>Aula 10/03/2026 <i class="correto_circulo"></i></div>'
        result = api.inspect_correto_circulo_by_card(
            page, [item("10/03/2026", "")])
        self.assertEqual(result["estado"], "estrutura_nao_validada")
        self.assertEqual(result["itens"], [])

    def test_no_items_does_not_infer_submission(self):
        result = api.inspect_correto_circulo_by_card(
            '<div>Nenhum planejamento encontrado</div>', [])
        self.assertEqual(result["estado"], "sem_atividades")
        self.assertEqual(result["itens"], [])

    def test_unterminated_card_is_indeterminate(self):
        html = ('<div class="card mr-2 va-plan-card">'
                '<span class="correto_circulo">Aula 10/03/2026</span>')
        result = api.inspect_correto_circulo_by_card(
            html, [item("10/03/2026", "")])
        self.assertEqual(result["estado"], "estrutura_nao_validada")


if __name__ == "__main__":
    unittest.main()
