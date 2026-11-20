# Vestibulare para Home Assistant (0.1.1 — candidata à implantação)

Integração personalizada experimental para consultar planejamentos abertos do portal Vestibulare, sem scripts externos, MQTT ou API oficial. Não tem vínculo com o fornecedor.

## Instalação

Adicione este repositório como integração personalizada no HACS/Marketplace, usando a branch main. Após o download, pode ser necessário reiniciar o Core do Home Assistant. Em Configurações > Dispositivos e serviços > Adicionar integração, procure Vestibulare. Informe a URL HTTPS do seu portal (ex.: https://escola.vestibulare.com.br/va), seu login e senha. Não coloque credenciais no GitHub.

A consulta ocorre a cada 15 minutos, usando os 11 IDs de disciplinas do perfil original. Os sensores de hoje, amanhã e atrasadas se referem aos prazos de atividades abertas; o sensor de atividades em aberto inclui a lista em seu atributo atividades. Os atributos `disciplinas_consultadas` e `atividades_por_disciplina` permitem comprovar que todas as 11 disciplinas foram percorridas, inclusive quando não há atividades. Uma falha intermediária não é convertida silenciosamente em lista vazia. Não envia notificações automaticamente. A sessão HTTP pertence ao Home Assistant, permanece disponível entre as consultas e é encerrada pelo próprio HA no desligamento, não pelo polling.

**Versão experimental:** o HTML real completo e o marcador de lista vazia ainda precisam ser validados. Respostas não reconhecidas falham de forma explícita em vez de retornar uma lista vazia incorreta. A integração não foi homologada em um Home Assistant real.

## Testes locais
```sh
python -m pip install aiohttp
python -m unittest discover -s tests -v
```
Testes usam dados fictícios e servidor HTTP local. Não autenticam no portal real.

## Privacidade
O login e a senha são armazenados pelo Home Assistant na configuração local (não criptografados por esta integração). Não há telemetria. Os dados das atividades podem ficar no histórico e backups locais do Home Assistant; proteja o acesso a estes dados.

## Diagnóstico do ícone de conclusão (em desenvolvimento)

O visto verde exibido no cartão de Planejamentos do aplicativo **não será
interpretado automaticamente como entrega** sem validação do seu significado.
O portal expõe marcadores distintos va-card-lido-inferior e
va-card-nao-lido-inferior; estes marcam leitura, não entrega.

A coleta diagnóstica experimental registra somente os nomes de classes/atributos
relacionados a status e eventuais nomes predefinidos de ícones, sem HTML bruto,
dados pessoais, sessão, URLs de recursos ou credenciais. Os indicadores serão
comparados entre planejamentos concluídos e não concluídos antes de alterar
a automação de alertas. Nenhuma entrega é inferida nesta versão diagnóstica.
