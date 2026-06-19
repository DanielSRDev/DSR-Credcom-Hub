"""
Serviços compartilhados pelos módulos de cards (Operação e Gestão).
"""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from .models import ConfiguracaoSeguranca


def finalizar_executados_vencidos(TarefaModel, ComentarioModel=None) -> int:
    """
    Finaliza automaticamente os cards que estão em EXECUTADO há mais tempo que
    o prazo de validação (ConfiguracaoSeguranca.prazo_validacao_dias).

    O carimbo `finalizado_em` recebe o momento real do vencimento
    (executado_em + prazo), e não o instante da varredura — assim o horário
    fica correto mesmo que a função só rode dias depois.

    Idempotente: roda a cada abertura do quadro/KPIs e também via management
    command. Retorna a quantidade de cards finalizados nesta passada.
    """
    dias = ConfiguracaoSeguranca.get_solo().prazo_validacao_dias or 2
    limite = timezone.now() - timedelta(days=dias)

    vencidos = list(
        TarefaModel.objects.filter(status="executado", executado_em__lt=limite)
    )

    for tarefa in vencidos:
        tarefa.status = "feita"
        tarefa.finalizado_em = tarefa.executado_em + timedelta(days=dias)
        tarefa.finalizado_automaticamente = True
        tarefa.save(update_fields=["status", "finalizado_em", "finalizado_automaticamente"])

        if ComentarioModel is not None:
            ComentarioModel.objects.create(
                tarefa=tarefa,
                autor=None,
                texto=(
                    f"Finalizado automaticamente por falta de validação "
                    f"em {dias} dia(s)."
                ),
            )

    return len(vencidos)
