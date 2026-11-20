# Vestibulare para Home Assistant (0.1.6 — associação segura por cartão único)

Integração personalizada experimental para consultar planejamentos abertos do portal Vestibulare, sem scripts externos, MQTT ou API oficial. Não tem vínculo com o fornecedor.

## Instalação

Adicione este repositório como integração personalizada no HACS/Marketplace, usando a branch main. Após o download, pode ser necessário reiniciar o Core do Home Assistant. Em Configurações > Dispositivos e serviços > Adicionar integração, procure Vestibulare. Informe a URL HTTPS do seu portal (ex.: https://escola.vestibulare.com.br/va), seu login e senha. Não coloque credenciais no GitHub.

A consulta ocorre a cada 15 minutos, usando os 11 IDs de disciplinas do perfil original. Os sensores de hoje, amanhã e atrasadas se referem aos prazos de atividades abertas; o sensor de atividades em aberto inclui a lista em seu atributo atividades. Os atributos `disciplinas_consultadas` e `atividades_por_disciplina` permitem comprovar que todas as 11 disciplinas foram percorridas, inclusive quando não há atividades. Uma falha intermediária não é convertida silenciosamente em lista vazia. Não envia notificações automaticamente. A sessão HTTP pertence ao Home Assistant, permanece disponível entre as consultas e é encerrada pelo próprio HA no desligamento, não pelo polling.

**Versão experimental:** o HTML real completo e o marcador de lista vazia ainda precisam ser validados. Respostas não reconhecidas falham de forma explícita em vez de retornar uma lista vazia incorreta. A integração de coleta de planejamentos já foi instalada e observada no Home Assistant da família. A nova descoberta autenticada de entregas desta versão ainda não foi implantada nem validada no portal real.

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

A coleta diagnóstica experimental registra, por disciplina (não por cartão), somente os nomes de classes/atributos
relacionados a status e eventuais nomes predefinidos de ícones, sem HTML bruto,
dados pessoais, sessão, URLs de recursos ou credenciais. Os indicadores serão
comparados entre planejamentos concluídos e não concluídos antes de alterar
a automação de alertas. Nenhuma entrega é inferida nesta versão diagnóstica.

Os indicadores visuais são agrupados por página da disciplina; não se atribui nenhum marcador a uma tarefa individual sem estrutura comprovada. Marcadores antigos potencialmente livres foram removidos da resposta diagnóstica. Negação como 'não entregue' é preservada como estado distinto.


## Diagnóstico 0.1.3 — descoberta de entrega automática

Sem modificar tarefas nem enviar formulários, as consultas autenticadas
das páginas Arte e Língua Portuguesa extraem somente caminhos de recursos
estáticos, nomes de handlers e campos selecionados e contagens limitadas
de formulários/botões. Valores de campos, argumentos JS, queries, HTML
e nomes de alunos nunca são enviados ao HA. Não confirma entrega:
somente ajuda a localizar um endpoint de leitura apropriado. Coleta
restrita às duas disciplinas com atividades no perfil atual; expansão
depende de evidências reais. A leitura não chama novas rotas.
\nPor segurança, o diagnóstico não guarda paths nem handlers completos; os resultados são agrupados em um vocabulário fixo e limitados a oito categorias por seção.\n

## Investigação automática de entrega 0.1.4

A rotina de consulta dos 11 planejamentos permanece independente. Depois da coleta, uma investigação **somente leitura** tenta localizar o menu autenticado do VA em caminhos conhecidos e, quando o próprio menu oferece um link estático seguro para o Mural/Entregas, faz uma única consulta GET daquela página. São recusados caminhos com IDs, parâmetros, ações de envio, exclusão ou edição e URLs de outros domínios.

O sensor traz apenas `investigacao_envio` com categorias e contagens limitadas; HTML bruto, textos escolares, links, credenciais, cookies e identificadores nunca são publicados em atributos. O resultado é armazenado em memória por seis horas para evitar requisições desnecessárias. Uma falha dessa investigação não bloqueia a sincronização dos planejamentos.

**Importante:** localizar uma rota de Mural e observar palavras como *enviado* ou *recebido* não comprova que um planejamento específico foi entregue. O status permanece **não verificado** e as tarefas não são encerradas por leitura do cartão. Somente após identificar e correlacionar um registro individual de envio será adicionada a atualização automática dos lembretes.

Testes isolados estão em `tests/test_delivery_discovery.py` e na rotina GitHub Actions. Nenhum servidor Codex ou Home Assistant precisa ser acessado diretamente para executá-los.

## Diagnóstico 0.1.5 — `correto_circulo`

Foi fornecido um script shell que procura `correto_circulo` no HTML de cada planejamento e assume que significa "feita". **Isso é hipótese, não comprovação de entrega**. A classe pode marcar outra condição e, como as telas usam `lido` para leitura, ambos são mantidos rigorosamente separados.

A integração 0.1.5 adiciona `diagnostico_correto_circulo` aos atributos do sensor de atividades em aberto. O coletor encontra os cartões pelo conjunto de classes `card mr-2 va-plan-card`, percorre os elementos dentro dos limites de cada cartão e só vincula o indicador à atividade quando a sequência e o par aula/prazo são unívocos. Quando o HTML é ambíguo, informa `estrutura_nao_validada` e não infere nada.

O atributo exibe apenas presença/ausência do marcador na classe, ID ou recurso de cada cartão; nunca publica HTML, cookies ou nomes extras. `status_entrega` continua `nao_verificado`. A automação de alertas permanece intacta; nenhum item da lista local é concluído com base no marcador até que ele seja correlacionado com evidência real de envio e de não envio.

Essa detecção substitui a heurística do script de dividir HTML usando `sed`, mas não executa o script nem cria arquivos de sessão. Testes em `tests/test_card_completion_probe.py` cobrem contaminação entre cartões, divergência de data/prazo, duplicidades e HTML malformado.

## Ajuste 0.1.6

Quando o HTML autenticado traz **exatamente um cartão real e um planejamento**, o diagnóstico pode associá-los por cardinalidade, mesmo que o texto extraído do cartão esteja incompleto. Datas ou prazos explícitos divergentes, cartão não fechado e cartões aninhados continuam bloqueando a associação. Para mais de um cartão continuam obrigatórios data/prazo únicos e estrutura íntegra. Marcador `correto_circulo` continua como sinal de acompanhamento definido pela família, não como comprovação formal de envio. Nenhuma alteração em automações ou remessas ao portal é feita pelo código da integração.
