# Proteção de dados no cruzamento de bases cadastrais

Esta nota descreve como um cruzamento de cadastros de pessoas, como o demonstrado neste projeto,
deve ser conduzido à luz da **Lei Geral de Proteção de Dados (Lei 13.709/2018, LGPD)**. O projeto
usa apenas dados sintéticos. A nota é um roteiro técnico e de governança, **não um parecer
jurídico**: cada cruzamento real precisa da análise do encarregado (DPO) e da área jurídica das
organizações envolvidas.

> **Contexto de organizações internacionais.** Agências da ONU, como o ACNUR, seguem as próprias
> políticas de proteção de dados, em razão de seus privilégios e imunidades. Órgãos públicos e
> organizações da sociedade civil no Brasil seguem a LGPD. Num cruzamento entre esses atores, o
> acordo de compartilhamento precisa conciliar os dois marcos e deixar explícito o mais restritivo.

---

## 1. Finalidade e base legal

O cruzamento só se justifica com uma **finalidade específica, explícita e informada** (art. 6º, I).
"Melhorar a qualidade dos dados" é vago demais. Exemplos de finalidades adequadas:

| Finalidade | Exemplo |
|---|---|
| Evitar duplicidade de assistência | Identificar pessoas que já recebem um benefício de outro programa |
| Garantir acesso a direitos | Encontrar pessoas do cadastro operacional que ainda não constam da lista governamental de um programa |
| Qualidade e continuidade do atendimento | Unificar o histórico de uma pessoa registrada mais de uma vez (deduplicação) |

**Bases legais possíveis** (a escolha depende de quem é o controlador e da finalidade):

| Situação | Base legal (LGPD) |
|---|---|
| Órgão público executando política pública prevista em lei | Art. 7º, III, e art. 23 (tratamento pelo poder público); uso compartilhado nos termos dos arts. 25 a 27 |
| Cumprimento de obrigação legal ou regulatória | Art. 7º, II |
| Organização da sociedade civil em convênio com o poder público | Art. 7º, III, quando o tratamento for necessário à execução do convênio |
| Dados sensíveis envolvidos (ex.: origem racial ou étnica, saúde) | Art. 11, II, "b" (políticas públicas) ou outra hipótese do art. 11 |
| Consentimento | Art. 7º, I: em geral **inadequado** em contexto humanitário, porque a pessoa raramente pode recusar sem perder o atendimento; não é livre |

**Atenção a dados sensíveis.** Nacionalidade e condição de refugiado não estão listadas no art. 5º,
II, mas podem revelar origem étnica e expor a pessoa a riscos graves. Trate-as com o mesmo cuidado
de um dado sensível e **não as use no cruzamento** quando não forem necessárias.

## 2. Minimização (art. 6º, III)

O cruzamento usa só o necessário para identificar a mesma pessoa:

| Campo | Usado | Por quê |
|---|---|---|
| Nome completo, nome da mãe | Sim | Identificação; o nome da mãe desempata homônimos |
| Data de nascimento, sexo | Sim | Identificação e blocagem |
| Município e UF | Sim | Blocagem e desempate |
| Documento | Sim, quando existe | Evidência forte; ausente em 40% da lista governamental |
| Nacionalidade, etnia, religião, situação migratória, saúde, endereço, telefone | **Não** | Não ajudam a identificar e aumentam o dano em caso de vazamento |

Regras práticas:

- cada organização **extrai só esses campos** antes de enviar a base, e nunca a base completa;
- as saídas trazem os **identificadores** dos registros e a pontuação; os campos em claro aparecem
  apenas na fila de revisão, que tem acesso restrito (seção 5);
- a tabela final de correspondências (`id_a`, `id_b`) é o único produto que precisa permanecer.

## 3. Papéis

| Papel (LGPD) | Quem, num cruzamento típico | Responsabilidades |
|---|---|---|
| **Controlador** (art. 5º, VI) | Cada organização dona de uma base. Se as duas definem juntas a finalidade, são **controladoras conjuntas** | Definir finalidade e base legal, aprovar o acordo, responder aos titulares, decidir a retenção |
| **Operador** (art. 5º, VII; art. 39) | A equipe técnica ou o fornecedor que executa o cruzamento por conta dos controladores | Seguir as instruções por escrito, não usar os dados para outro fim, manter a segurança e apagar os dados ao final |
| **Encarregado (DPO)** (art. 41) | Indicado por cada controlador | Avaliar o cruzamento, recomendar o relatório de impacto (art. 38) e atender os titulares |
| **Revisores** | Pessoas designadas pelo controlador | Decidir os pares da fila de revisão, sob termo de confidencialidade |

Quem executa o cruzamento **não decide a finalidade**. Se a equipe técnica passa a usar o resultado
para outro objetivo, ela deixa de ser operadora e passa a responder como controladora.

## 4. Registro do cruzamento (art. 37)

Toda execução deve deixar um registro da operação. O `rlk link` já grava parte dele em
`reports/resumo_link.json` (seção `registro`): versão da ferramenta, **hash SHA-256 de cada base
usada** (prova qual versão foi cruzada, sem copiar o conteúdo), hash da configuração, campos e regras
de blocagem. O responsável completa os demais campos:

| Campo | Exemplo |
|---|---|
| Data e responsável | 05/11/2026, equipe de gestão da informação |
| Finalidade | Evitar duplicidade de assistência no programa X |
| Base legal | Art. 7º, III, e acordo de cooperação nº ... |
| Bases cruzadas e hashes | `resumo_link.json` → `registro.arquivos` |
| Parâmetros | `config/default.yaml` (hash em `registro.configuracao_sha256`) |
| Resultado | Pares automáticos, pares revisados, decisão dos revisores |
| Destinatários do resultado | Quem recebe a tabela de correspondências e para quê |
| Prazo de retenção e data de descarte | Ver seção 6 |

## 5. Fila de revisão manual

### Por que existe revisão humana

- **Erros têm consequências para pessoas.** Um falso positivo funde duas pessoas: uma delas pode
  perder um benefício ou herdar o histórico da outra. Um falso negativo pode duplicar assistência ou
  deixar alguém "invisível" para um programa.
- **Há casos que nenhum limiar resolve.** No relatório, os falsos positivos com pontuação alta são
  gêmeos sintéticos: mesma mãe, mesma data e mesmo município, só o primeiro nome muda. Sem documento,
  o modelo não tem como separá-los; uma pessoa, com contexto, tem.
- **Direito à revisão** (art. 20): o titular pode pedir a revisão de decisões tomadas unicamente com
  base em tratamento automatizado que afetem seus interesses. Manter uma faixa de revisão humana e
  registrar a decisão é a forma prática de cumprir esse dever.

### Quem acessa

| Regra | Como aplicar |
|---|---|
| Necessidade de saber | Apenas os revisores designados (de preferência dois, com dupla checagem nos casos sensíveis) |
| Confidencialidade | Termo assinado; a fila não sai do ambiente controlado (sem e-mail, sem pendrive) |
| Menor exposição | A fila mostra só os campos usados na comparação; nunca a base completa |
| Rastreabilidade | A coluna `decisao_revisor` é preenchida com a decisão e o revisor é registrado |
| Descarte | A fila é apagada assim que as decisões são incorporadas à tabela de correspondências |

## 6. Retenção

| Artefato | Conteúdo | Retenção sugerida |
|---|---|---|
| Extratos enviados por cada organização | Campos mínimos de identificação | Apagar ao fim do cruzamento |
| `candidatos.csv`, `candidatos_dedup.csv` | Pares comparados e pontuações | Apagar ao fim da avaliação |
| `revisao_manual.csv` | Campos em claro, lado a lado | Apagar após as decisões serem incorporadas |
| `nao_pareados.csv` | Registros sem par | Apagar ao fim do cruzamento; o controlador mantém só o que a finalidade exige |
| `matches.csv` (tabela de correspondências) | `id_a`, `id_b`, pontuação | Enquanto durar a finalidade, conforme o acordo |
| Hashes do modo pseudonimizado | Chaves com hash | Apagar logo após o pareamento |
| Sal secreto | Segredo compartilhado | **Destruir** ao final; um novo cruzamento usa um novo sal |
| `resumo_link.json` (registro) | Hashes de arquivos, parâmetros, contagens | Guardar como registro da operação (sem dados pessoais) |

## 7. Modo pseudonimizado

### Como funciona

`rlk pseudo` permite que duas organizações cruzem bases **sem trocar nomes em claro**:

1. As organizações combinam um **sal secreto** fora de qualquer repositório (por exemplo, entregue
   pessoalmente ou por um canal cifrado) e o guardam na variável de ambiente `RLK_SALT`.
2. Cada uma padroniza a própria base (maiúsculas, sem acentos, sem partículas, datas em ISO,
   chave fonética) e calcula o **SHA-256 com o sal** de quatro chaves: documento; nome + data;
   nome fonético + data + nome fonético da mãe; nome fonético + ano + sexo + município. O sal é
   aplicado na forma HMAC-SHA256, a construção padrão para hash com segredo.
3. Só os arquivos de hashes (`id` + chaves) são trocados. O pareamento é exato, em cascata, e um
   hash repetido de um dos lados é ignorado por ser ambíguo.

Sem `RLK_SALT`, o comando falha de propósito. O `make run` gera um sal efêmero em memória, só para a
demonstração, que não é gravado em lugar nenhum.

### Limites

| Limite | O que significa | Mitigação |
|---|---|---|
| **Ataque de dicionário** | Nomes e datas formam um espaço pequeno. Quem tem o sal pode gerar hashes de uma lista de nomes candidatos e descobrir quem está na outra base. A outra organização **tem o sal**. | Acordo que proíba a reidentificação; sal guardado por um terceiro de confiança, que recebe os hashes e devolve só os pares; destruir o sal ao final |
| **Continua sendo dado pessoal** | Hash com sal é pseudonimização, não anonimização (art. 12 e art. 13, § 4º). A LGPD se aplica integralmente. | Mesmo cuidado da base em claro: base legal, acordo, segurança e retenção |
| **Precisa de acordo de compartilhamento** | Esconder os nomes não substitui a base legal nem o acordo entre as partes. | Acordo com finalidade, campos, proibição de reidentificação, retenção, destruição do sal e direito de auditoria |
| **Perda do pareamento aproximado** | Um erro de digitação ou uma data diferente gera outro hash. Nos dados sintéticos, a cascata de chaves acerta 100% dos pares que encontra, mas o recall cai para **83,6%**, contra **95,2%** do modo aproximado automático e **99,4%** com revisão manual (números em `reports/metricas.json`). | Usar a chave fonética; aceitar a perda como custo da privacidade; avaliar técnicas de *privacy-preserving record linkage* com filtros de Bloom (próximo passo do projeto) |
| **Ataque de frequência** | Sobrenomes muito comuns geram hashes muito frequentes, o que dá pistas mesmo sem o sal. | Não divulgar os arquivos de hashes; combinar chaves para reduzir as repetições |

## 8. Checklist antes de um cruzamento real

- [ ] Finalidade específica escrita e aprovada pelos controladores.
- [ ] Base legal definida para cada organização (e para dados sensíveis, se houver).
- [ ] Acordo de compartilhamento assinado (finalidade, campos, papéis, retenção, auditoria).
- [ ] Relatório de impacto (art. 38) avaliado pelo encarregado.
- [ ] Extratos com os campos mínimos, nunca a base completa.
- [ ] Ambiente controlado para o cruzamento e a fila de revisão.
- [ ] Revisores designados, com termo de confidencialidade.
- [ ] Limiares validados numa amostra rotulada antes de aceitar matches automáticos.
- [ ] Registro do cruzamento preenchido (seção 4).
- [ ] Datas de descarte agendadas para cada artefato (seção 6).
