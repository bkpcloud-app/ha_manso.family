"""Native sensors backed by a single polling coordinator."""
from datetime import datetime, timedelta
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

SENSORS = {"abertas":"Atividades em aberto", "hoje":"Atividades para hoje", "amanha":"Atividades para amanhã", "atrasadas":"Atividades atrasadas", "proxima":"Próximo prazo", "sincronizacao":"Última sincronização"}

async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([VestibulareSensor(entry, key) for key in SENSORS])

class VestibulareSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, entry, key):
        super().__init__(entry.runtime_data)
        self.key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = f"Vestibulare {SENSORS[key]}"
        if key in ("proxima", "sincronizacao"):
            self._attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self):
        if self.key == "sincronizacao":
            return self.coordinator.data["synced"]
        items = self.coordinator.data["items"]
        if self.key == "abertas":
            return len(items)
        now = dt_util.now()
        dates = [datetime.strptime(item["prazo"], "%d/%m/%Y %H:%M").replace(tzinfo=now.tzinfo) for item in items if item["prazo"]]
        if self.key == "hoje":
            return sum(d.date() == now.date() for d in dates)
        if self.key == "amanha":
            return sum(d.date() == now.date() + timedelta(days=1) for d in dates)
        if self.key == "atrasadas":
            return sum(d < now for d in dates)
        next_due = min((d for d in dates if d >= now), default=None)
        return dt_util.as_utc(next_due) if next_due is not None else None

    @property
    def extra_state_attributes(self):
        if self.key == "abertas":
            counts = self.coordinator.data.get("counts", {})
            return {"atividades": self.coordinator.data["items"],
                    "disciplinas_consultadas": len(counts),
                    "atividades_por_disciplina": counts,
                    "status_entrega": "nao_verificado",
                    "indicadores_para_diagnostico": self.coordinator.data.get("submission_probe", []),
                    "indicadores_visuais_por_disciplina": self.coordinator.data.get("visual_probe", []),
                    "navegacao_portal_diagnostico": self.coordinator.data.get("navigation_probe", []),
                    "investigacao_envio": self.coordinator.data.get("delivery_navigation", {"estado": "nao_executado"}),
                    "diagnostico_correto_circulo": self.coordinator.data.get("correto_probe", [])}
        return None
