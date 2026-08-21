================================================================================
                        HYPERNIX DUAL LICENSE
================================================================================

Copyright 2026 HyperNix contributors

This software ("the Software") is made available to You under the terms of
either of the following licenses, at Your option:

  (A) HyperNix OpenCode Light Limited Use License, Version 0.1 (LLU-0.1)
      — a source-available license with transparency and use-restriction
        conditions; or

  (B) HyperNix Open Source License, Version 1.0 (HOS-1.0)
      — an OSI-compliant open-source license without field-of-use restrictions.

You must elect one license and comply with its terms. You may not combine,
merge, or cherry-pick terms from both licenses. If You do not make an active
choice, the default license that applies to You is (A) LLU-0.1.

Contributions submitted to the project are accepted under both licenses
unless the Contributor explicitly states otherwise.

================================================================================
OPTION (A): HYPERNIX OPENCODE LIGHT LIMITED USE LICENSE v0.1 (LLU-0.1)
================================================================================

Copyright 2026 HyperNix contributors

This License is a heavily modified version of the Apache License, Version
2.0 — its structure and copyright/patent grants share that lineage, but
this document is self-contained: nothing in it is incorporated by
reference from any other license, and it should be read on its own terms.

**Note on open-source status.** This License does not meet the Open
Source Initiative's Open Source Definition or the Free Software
Foundation's Free Software Definition, because §12 restricts specific
fields of use. "OpenCode" refers to the public availability of the
Software's source code, not to certification as "open source" or "free
software" in that formal sense. This License is more accurately described
as a source-available license with use restrictions. However, because
this Software is offered under a dual-license framework, You may instead
choose Option (B) above if You require OSI-approved open-source terms.

## 1. Definitions

**"License"** means the terms and conditions set out in this document.

**"Licensor"** means HyperNix contributors, the copyright owner(s) of the
Software.

**"You" ("Your")** means an individual or Legal Entity exercising
permissions granted by this License.

**"Legal Entity"** means an entity, together with all other entities that
control, are controlled by, or are under common control with that entity
(its "Affiliates"), where "control" means direct or indirect ownership of
more than fifty percent (50%) of the entity's outstanding equity or
voting interests, or the contractual right to direct its management.
Actions taken by, or sharing among, Affiliates of the same Legal Entity
are treated as actions of a single Legal Entity under this License.

**"Software" ("Work")** means the HyperNix source code, scripts,
documentation, and associated files made available under this License,
in either Source or Object form, as indicated by a copyright notice
included in or attached to the work.

**"Source"** form means the preferred form for making modifications,
including source code, configuration files, and documentation source.

**"Object"** form means any form resulting from mechanical transformation
or translation of a Source form, including compiled object code,
generated documentation, and conversions to other media types.

**"Derivative Works"** means any work, in Source or Object form, that is
based on or derived from the Software, including modified copies,
editorial revisions, and works into which the Software has been
incorporated in whole or part.

**"Fork"** means a copy of the Software's Source form maintained,
published, or distributed as a separate project or repository, whether
or not modified — including a version that has been substantially
rewritten, refactored, or reimplemented, if its development involved
copying, translating, or adapting a material portion of the Software's
Source form, architecture, or design, rather than being independently
authored. A work that merely uses an unmodified copy of the Software as
a dependency, or that was independently developed without copying a
material portion of the Software's Source form, is not a Fork.

**"Contribution"** means any work of authorship, including the original
version of the Software and any modifications or additions to it, that
is intentionally submitted to the Licensor for inclusion in the
Software by the copyright owner or by an individual/entity authorized
to submit on their behalf.

**"Contributor"** means the Licensor and any individual or Legal Entity
on whose behalf a Contribution has been received and subsequently
incorporated within the Software.

**"Trained Model"** means any machine learning model — including without
limitation a Small Language Model (SLM), Medium Language Model, or Large
Model as described in §7-8 — that is trained, fine-tuned, distilled, or
otherwise produced in whole or Material Part using the Software.

**"Material Part"** means the Software, or a Derivative Work of it, was
used for a step that shapes the Trained Model's parameters or training
data — including initialization, the training or fine-tuning loop,
optimizer logic, data curation or curriculum tooling, or checkpoint
conversion — regardless of how small a proportion of the Trained Model's
total development time, cost, or compute that step represents. Using the
Software only for something that does not affect the Trained Model's
parameters or training data (e.g. an unrelated utility script) is not
use of a Material Part.

**"Original Creator"** means the individual(s) or Legal Entity that
first trains a given Trained Model.

**"Weight-Level Sharing"** means making a Trained Model's parameter
weights, or functional access sufficient to run, query, or otherwise
directly use the Trained Model (e.g. a hosted API, a downloadable
checkpoint, or a product built directly on it), available to any person
or entity other than its Original Creator.

**"Documentation-Level Sharing"** means making a model or system card,
sample outputs, or a technical paper/report about a Trained Model
available to any person or entity other than its Original Creator,
without also engaging in Weight-Level Sharing of that Trained Model.

For purposes of both Sharing definitions: making a Trained Model
available only among Affiliates of the Original Creator's own Legal
Entity is not Sharing. Making it available to a contractor, vendor, or
other service provider **is** Sharing, even if performed "on the Original
Creator's behalf," unless that party is contractually bound to (i) use
the Trained Model solely for the Original Creator's benefit, (ii) not
retain, deploy, or further distribute it beyond that engagement, and
(iii) keep it confidential.

**"Full Release Version"** means a version of the Software numbered
0.71.4 or higher under the Software's official versioning scheme,
excluding alpha, beta, dev, nightly, and release-candidate builds.

**"Open Source"**, as applied to a Trained Model's training or inference
code, means released under an OSI-approved or substantially equivalent
open license. **"Open Weight"** means the Trained Model's parameter
weights are made publicly downloadable, with or without an open license
governing the weights themselves.

**"Parameters"** means the total count of trainable weights in a Trained
Model, counting every weight regardless of whether it is active for any
given inference pass — for a mixture-of-experts or other conditionally-
activated architecture, this means the sum of all expert/parameter sets
in the model, not merely the subset routed per token or per input. This
figure is as reported by the model's own configuration/card, or a
reasonable good-faith estimate where no such figure is published.

**"Primary Training Data Sources"** means the principal datasets, corpora,
or data-collection sources that make up the majority (by token or sample
count) of a Trained Model's training data — e.g. named public datasets,
a documented description of a proprietary corpus, or the identified
domains/categories of crawled data. This does not require publishing the
raw data itself, only information sufficient to identify its origin and
general composition.

**"Data Composition Summary"** means, at minimum, an approximate
percentage breakdown of the categories of data used to train a Trained
Model — including the approximate share that is scraped or crawled web
data, the approximate share that is human-authored or human-curated data
(e.g. licensed text, human-written code), and the approximate share that
is synthetic or model-generated data — sufficient to give a reader a
general sense of the training mix without necessarily naming every
specific source.

**"Malicious Use"** has the meaning given in §12.

## 2. Grant of Copyright License

Subject to the terms of this License, each Contributor grants You a
perpetual, worldwide, non-exclusive, royalty-free, irrevocable copyright
license to reproduce, prepare Derivative Works of, publicly display,
publicly perform, sublicense, and distribute the Software and such
Derivative Works, in Source or Object form.

## 3. Grant of Patent License

Subject to the terms of this License, each Contributor grants You a
perpetual, worldwide, non-exclusive, royalty-free, irrevocable (except as
stated in this section) patent license to make, have made, use, offer to
sell, sell, import, and otherwise transfer the Software, where such
license applies only to patent claims licensable by that Contributor
that are necessarily infringed by their Contribution(s) alone or in
combination with the Software. If You institute patent litigation
against any entity alleging that the Software or a Contribution
constitutes patent infringement, any patent licenses granted to You
under this License for that Software terminate as of the date such
litigation is filed.

## 4. Redistribution

You may reproduce and distribute copies of the Software or Derivative
Works in any medium, with or without modifications, in Source or Object
form, provided You meet all of the following conditions:

**(a)** You give any other recipients of the Software or Derivative
Works a copy of this License;

**(b)** You cause any modified files to carry prominent notices stating
that You changed them;

**(c)** You retain, in the Source form of any Derivative Works You
distribute, all copyright, patent, trademark, and attribution notices
from the Source form of the Software, excluding notices that do not
pertain to any part of the Derivative Works;

**(d)** If the Software is distributed with a "NOTICE" text file, any
Derivative Works You distribute must include a readable copy of the
attribution notices it contains, in at least one customary place such
notices appear;

**(e) Same-License Forks.** Any Fork of the Software — the whole project
or a substantial part of it, modified or unmodified — that You publish
or distribute must be licensed in its entirety under this same HyperNix
OpenCode Light Limited Use License v0.1 (LLU-0.1), and may not be
relicensed under a different license or have additional restrictive
terms layered on top. This condition applies only to the Software and
Forks of it, not to independent applications that merely use the
Software as a dependency.

You may add Your own copyright statement to Your modifications, and may
offer additional or different license terms for use, reproduction, or
distribution of a Derivative Work as a whole that is not itself a Fork
under (e) — provided Your use, reproduction, and distribution of the
Software otherwise complies with this License.

## 5. Contributions

Unless You explicitly state otherwise, any Contribution You intentionally
submit for inclusion in the Software is provided under the terms of this
License, without any additional terms or conditions, notwithstanding
anything above.

## 6. Trademarks

This License does not grant permission to use the trade names,
trademarks, service marks, or product names of the Licensor (including
"HyperNix", "hyped", "hyped+", "hyped-pro", "hyped-plus", and associated
logos), except as required for reasonable, customary description of the
Software's origin and reproduction of the NOTICE file's content.

A Fork or Derivative Work may not describe itself as "HyperNix," or use a
name confusingly similar to it, in a way that implies official origin or
endorsement, unless clearly distinguished (e.g. "MyProject, a fork of
HyperNix").

## 7. Recommended Openness for SLMs and Medium Language Models (Non-Binding)

Small Language Models and Medium Language Models trained using any Full
Release Version of the Software (v0.71.4 or higher) are **highly
recommended**, but not required, to be released as Open Source or Open
Weight. This section is aspirational guidance reflecting the project's
values; it does not create a binding obligation and is not enforceable as
a condition of this License.

## 8. Required Transparency for Large Models (Binding)

This section applies only to a Trained Model with more than
29,100,000,000 (29.1 billion) Parameters, produced using the Software.

**(a) Fully private models are exempt.** If such a Trained Model involves
neither Weight-Level Sharing nor Documentation-Level Sharing, this
Section 8 imposes no obligation on You.

**(b) Weight-Level Sharing requires full disclosure.** If such a Trained
Model is made available through Weight-Level Sharing, You must publish
its Primary Training Data Sources in a reasonably accessible location
(e.g. a model card, repository README, or accompanying publication), at
or before the time it is first made available that way.

**(c) Documentation-Level Sharing requires, at minimum, a data
composition summary.** If such a Trained Model is made available only
through Documentation-Level Sharing — a model/system card, sample
outputs, or a paper, without Weight-Level Sharing — You are exempt from
the full Primary Training Data Sources disclosure required by (b), but
must instead publish, at minimum, a Data Composition Summary in that
same card, sample release, or paper, at or before the time it is first
made available.

**(d) Benchmarks alone trigger neither obligation.** Publishing
benchmark, leaderboard, or other aggregate performance results about the
Trained Model does not, by itself, constitute Weight-Level Sharing or
Documentation-Level Sharing under this section.

**(e) Escalation.** If a Trained Model that has only had Documentation-
Level Sharing is later made available through Weight-Level Sharing, the
full Primary Training Data Sources disclosure required by (b) becomes
due at that time, replacing the (c) minimum.

## 9. Truthful Disclosure

Any disclosure, representation, or claim You make under this License —
including a §8 Primary Training Data Sources disclosure, a §8 Data
Composition Summary, a §10 attribution statement, or any public
description of a Trained Model's provenance, training data,
capabilities, or limitations — must be accurate and not misleading.
Deliberately mischaracterizing whether or how a Trained Model has been
shared, what data it was trained on, or what it can do, in order to
avoid, narrow, or circumvent an obligation under this License, is a
material breach of this License, independent of and in addition to any
liability under other applicable law.

## 10. Attribution

In addition to the notices required by §4, any public distribution,
publication, or description of a Trained Model, tool, or product built
using the Software must:

**(a)** give reasonable credit to the HyperNix project (e.g. "trained
with HyperNix" or equivalent), in a manner appropriate to the medium;

**(b)** provide a link to, or copy of, this License; and

**(c)** indicate if changes were made to the Software itself.

You may satisfy this section in any reasonable manner, but not in a way
that suggests the Licensor endorses You or Your use.

## 11. No Endorsement / No Misrepresentation

You may not state or imply that the Licensor or HyperNix contributors
sponsor, endorse, fund, or are affiliated with Your Trained Model, Fork,
product, or service, beyond the factual attribution required by §10,
without separate written permission.

## 12. Prohibited Uses

Regardless of whether a Trained Model is shared, kept entirely private,
or used solely by its Original Creator — there is no private-use
exemption from this section, subject only to §12(f) below — You may not
use the Software to train, fine-tune, or otherwise produce a Trained
Model for, and may not use any Trained Model produced using the Software
to engage in or facilitate, any of the following ("Malicious Use"):

**(a)** gaining or attempting to gain unauthorized access to, or
disrupting, a computer system, network, or account ("hacking"), or
generating malware, exploits, or intrusion tooling directed at such
systems;

**(b)** fraud, phishing, financial scams, or other deceptive schemes
intended to obtain money, property, or sensitive information from a
person or organization under false pretenses ("scamming");

**(c)** producing or distributing non-consensual synthetic media of a
real, identifiable person — including "deepfake" audio, image, or video
— where it is intended to deceive, defraud, harass, defame, or sexually
exploit that person;

**(d)** producing, or facilitating the production of, any content that
sexualizes or exploits minors, in any form;

**(e)** any other use that is unlawful in the jurisdiction where it
occurs, or that is intended to cause significant, unconsented physical,
financial, or psychological harm to a specific person or group.

**(f)** producing, hosting, or distributing sexual or pornographic
content of any kind — regardless of whether it depicts adults, minors,
real people, or purely fictional or synthetic subjects. This prohibition
is absolute: it does not depend on consent, on legality in any
jurisdiction, or on how open the Trained Model is.

**(g) Narrow exemption for fully open, immediately disclosed, and lawful
tools.** The restrictions in §12(a)-(c) and (e) do not apply to a
specific use of a Trained Model if, at all relevant times: (i) that
Trained Model's Primary Training Data Sources, architecture, and weights
are all 100% open — fully Open Source and Open Weight, with the actual
Primary Training Data Sources (not merely a Data Composition Summary)
publicly available; (ii) anyone accessing the Trained Model, or a
website/product offering it, is given conspicuous, unavoidable notice —
before or at the moment of first substantive interaction (e.g. a CLI
startup banner, a splash screen or modal shown before first use, or a
statement in the first visible paragraph of a landing page) — that it is
built for one of the purposes described in §12(a)-(c) or (e); a mention
that is only buried in a Terms of Service document, End User License
Agreement, or a page the user must separately navigate to does not
satisfy this requirement; and (iii) that specific use is otherwise
lawful. This exemption never applies to §12(d) or §12(f): no degree of
openness, disclosure, or claimed legality permits content that
sexualizes or exploits minors, or sexual content of any kind.

This section restricts how the Software and any resulting Trained Model
may be used; it does not, by itself, expand or limit the licenses
granted in §2-3.

## 13. No Additional Restrictions

You may not impose any additional terms, technical restrictions (such as
digital rights management), legal notices, or conditions on a recipient
of the Software or a Trained Model that would prevent that recipient
from exercising the rights this License grants them — except for the
license terms this License itself expressly allows You to add under §4.

## 14. Termination

Your rights under this License terminate automatically if You materially
breach it — including a violation of §4(e) (Same-License Forks), §8
(Required Transparency), §9 (Truthful Disclosure), or §12 (Prohibited
Uses) — and do not cure that breach within 30 days of becoming aware of
it. Sections 9, 11, 12, 15, 16, and 18(a) survive any termination of this
License. Termination does not affect the rights of any third party who
received the Software or a Derivative Work from You in compliance with
this License, prior to termination.

## 15. Disclaimer of Warranty

Unless required by applicable law or agreed to in writing, the Licensor
provides the Software on an "AS IS" BASIS, WITHOUT WARRANTIES OR
CONDITIONS OF ANY KIND, either express or implied, including, without
limitation, any warranties or conditions of TITLE, NON-INFRINGEMENT,
MERCHANTABILITY, or FITNESS FOR A PARTICULAR PURPOSE. You are solely
responsible for determining the appropriateness of using or
redistributing the Software, and assume any risks associated with Your
exercise of permissions under this License — including risks associated
with a Trained Model's outputs, biases, or downstream use.

## 16. Limitation of Liability

In no event and under no legal theory, whether in tort (including
negligence), contract, or otherwise, unless required by applicable law,
shall any Contributor be liable to You for damages, including direct,
indirect, special, incidental, or consequential damages of any character
arising as a result of this License, or out of the use or inability to
use the Software, even if such Contributor has been advised of the
possibility of such damages.

## 17. Accepting Warranty or Additional Liability

While redistributing the Software or Derivative Works, You may choose to
offer, and charge a fee for, acceptance of support, warranty, indemnity,
or other liability obligations consistent with this License. You may act
only on Your own behalf and on Your sole responsibility, not on behalf of
any other Contributor, and only if You agree to indemnify, defend, and
hold each Contributor harmless for any liability incurred by, or claims
asserted against, that Contributor by reason of Your accepting any such
warranty or additional liability.

## 18. Miscellaneous

**(a) Severability.** If any provision of this License is held
unenforceable, the remaining provisions remain in full force and effect.

**(b) No Waiver.** The Licensor's failure to enforce any provision of
this License is not a waiver of future enforcement of that or any other
provision.

**(c) Versioning.** This is version 0.1 of the HyperNix OpenCode Light
Limited Use License. The Licensor may publish revised versions, each
with its own version number. Software already distributed under LLU-0.1
remains governed by LLU-0.1 unless the Licensor explicitly relicenses
that specific release under a newer version.

**(d) Not Legal Advice.** This License is a project governance document,
not a substitute for independent legal review. The Licensor recommends
having it reviewed by a qualified attorney before relying on it for a
public release, particularly given §4(e)'s departure from purely
permissive licensing and the obligations in §8, §9, and §12.

**(e) Independent Contractual Undertaking.** To the extent any condition
of this License — including those in §4(e), §8, §9, or §12 — is found
unenforceable as a condition of the copyright or patent licenses granted
in §2-3, that condition instead constitutes a separate, independent
contractual obligation that You undertake by exercising any right this
License grants, enforceable as an ordinary contract term regardless of
its enforceability as a license condition.

================================================================================
OPTION (B): HYPERNIX OPEN SOURCE LICENSE v1.0 (HOS-1.0)
================================================================================

Copyright 2026 HyperNix contributors

This license is derived from the Apache License, Version 2.0. It is
intended to conform to the Open Source Definition as published by the
Open Source Initiative (OSI).

## 1. Definitions

"License" means the terms and conditions set out in this document.

"Licensor" means the copyright owner(s) of the Software.

"You" ("Your") means an individual or Legal Entity exercising permissions
granted by this License.

"Legal Entity" means an entity, together with all other entities that
control, are controlled by, or are under common control with that entity
(its "Affiliates"), where "control" means direct or indirect ownership
of more than fifty percent (50%) of the entity's outstanding equity or
voting interests, or the contractual right to direct its management.
Actions taken by, or sharing among, Affiliates of the same Legal Entity
are treated as actions of a single Legal Entity under this License.

"Software" ("Work") means the HyperNix source code, scripts,
documentation, and associated files made available under this License,
in either Source or Object form.

"Source" form means the preferred form for making modifications,
including source code, configuration files, and documentation source.

"Object" form means any form resulting from mechanical transformation
or translation of a Source form, including compiled object code,
generated documentation, and conversions to other media types.

"Derivative Works" means any work, in Source or Object form, that is
based on or derived from the Software, including modified copies,
editorial revisions, annotations, elaborations, and works into which
the Software has been incorporated, in whole or in part.

"Contribution" means any work of authorship, including the original
version of the Software and any modifications or additions to it, that
is intentionally submitted to the Licensor for inclusion in the Software
by the copyright owner or by an individual or Legal Entity authorized
to submit on their behalf.

"Contributor" means the Licensor and any individual or Legal Entity on
whose behalf a Contribution has been received by the Licensor and
subsequently incorporated within the Software.

## 2. Grant of Copyright License

Subject to the terms of this License, each Contributor grants You a
perpetual, worldwide, non-exclusive, royalty-free, irrevocable copyright
license to reproduce, prepare Derivative Works of, publicly display,
publicly perform, sublicense, and distribute the Software and such
Derivative Works, in Source or Object form.

## 3. Grant of Patent License

Subject to the terms of this License, each Contributor grants You a
perpetual, worldwide, non-exclusive, royalty-free, irrevocable (except
as stated in this section) patent license to make, have made, use, offer
to sell, sell, import, and otherwise transfer the Software, where such
license applies only to patent claims licensable by that Contributor that
are necessarily infringed by their Contribution(s) alone or in
combination with the Software. If You institute patent litigation
against any entity (including a cross-claim or counterclaim in a lawsuit)
alleging that the Software or a Contribution incorporated within the
Software constitutes direct or contributory patent infringement, then
any patent licenses granted to You under this License for that Software
shall terminate as of the date such litigation is filed.

## 4. Redistribution

You may reproduce and distribute copies of the Software or Derivative
Works thereof in any medium, with or without modifications, and in
Source or Object form, provided that You meet the following conditions:

(a) You must give any other recipients of the Software or Derivative
    Works a copy of this License; and

(b) You must cause any modified files to carry prominent notices stating
    that You changed the files; and

(c) You must retain, in the Source form of any Derivative Works that You
    distribute, all copyright, patent, trademark, and attribution notices
    from the Source form of the Software, excluding those notices that do
    not pertain to any part of the Derivative Works; and

(d) If the Software includes a "NOTICE" text file, then any Derivative
    Works that You distribute must include a readable copy of the
    attribution notices contained within such NOTICE file, in at least one
    of the following places: within a NOTICE text file distributed as
    part of the Derivative Works; within the Source form or
    documentation, if provided along with the Derivative Works; or,
    within a display generated by the Derivative Works, if and wherever
    such third-party notices normally appear. The contents of the NOTICE
    file are for informational purposes only and do not modify the
    License. You may add Your own attribution notices within Derivative
    Works that You distribute, alongside or as an addendum to the NOTICE
    text from the Software, provided that such additional attribution
    notices cannot be construed as modifying the License.

You may add Your own copyright statement to Your modifications and may
provide additional or different license terms and conditions for use,
reproduction, or distribution of Your modifications, or for any such
Derivative Works as a whole, provided Your use, reproduction, and
distribution of the Software otherwise complies with the conditions
stated in this License.

## 5. Submission of Contributions

Unless You explicitly state otherwise, any Contribution intentionally
submitted for inclusion in the Software by You to the Licensor shall be
under the terms and conditions of this License, without any additional
terms or conditions. Notwithstanding the above, nothing herein shall
supersede or modify the terms of any separate license agreement you may
have executed with Licensor regarding such Contributions.

## 6. Unique Naming

A Derivative Work may not describe itself as "HyperNix," or use a name
confusingly similar to it, in a way that implies official origin,
endorsement, or affiliation, unless clearly distinguished (e.g.
"MyProject, a fork of HyperNix").

## 7. No Endorsement

You may not state or imply that the Licensor or HyperNix contributors
sponsor, endorse, fund, or are affiliated with Your Derivative Work,
product, or service, beyond the factual attribution required by §4,
without separate written permission.

## 8. Termination

Your rights under this License terminate automatically if You fail to
comply with any of its terms and do not cure such breach within 30 days
of becoming aware of it. Sections 7, 9, 10, 11, and 12 survive any
termination of this License. Termination does not affect the rights of
any third party who received the Software or a Derivative Work from You
in compliance with this License prior to such termination.

## 9. Disclaimer of Warranty

Unless required by applicable law or agreed to in writing, the Licensor
provides the Software on an "AS IS" BASIS, WITHOUT WARRANTIES OR
CONDITIONS OF ANY KIND, either express or implied, including, without
limitation, any warranties or conditions of TITLE, NON-INFRINGEMENT,
MERCHANTABILITY, or FITNESS FOR A PARTICULAR PURPOSE. You are solely
responsible for determining the appropriateness of using or
redistributing the Software and assume any risks associated with Your
exercise of permissions under this License.

## 10. Limitation of Liability

In no event and under no legal theory, whether in tort (including
negligence), contract, or otherwise, unless required by applicable law
(such as deliberate and grossly negligent acts) or agreed to in
writing, shall any Contributor be liable to You for damages, including
any direct, indirect, special, incidental, or consequential damages of
any character arising as a result of this License or out of the use or
inability to use the Software (including but not limited to damages for
loss of goodwill, work stoppage, computer failure or malfunction, or any
and all other commercial damages or losses), even if such Contributor
has been advised of the possibility of such damages.

## 11. Accepting Warranty or Additional Liability

While redistributing the Software or Derivative Works thereof, You may
choose to offer, and charge a fee for, acceptance of support, warranty,
indemnity, or other liability obligations and/or rights consistent with
this License. However, in accepting such obligations, You may act only
on Your own behalf and on Your sole responsibility, not on behalf of
any other Contributor, and only if You agree to indemnify, defend, and
hold each Contributor harmless for any liability incurred by, or claims
asserted against, such Contributor by reason of Your accepting any such
warranty or additional liability.

## 12. Miscellaneous

(a) Severability. If any provision of this License is held to be
    unenforceable, such provision shall be reformed only to the extent
    necessary to make it enforceable, and the remaining provisions shall
    remain in full force and effect.

(b) No Waiver. The failure of any party to enforce any provision of this
    License shall not constitute a waiver of future enforcement of that
    or any other provision.

(c) Versioning. This is version 1.0 of the HyperNix Open Source License.
    The Licensor may publish revised versions from time to time. Each
    version will be given a distinguishing version number. Software
    already distributed under HOS-1.0 continues to be governed by
    HOS-1.0 unless the Licensor explicitly relicenses that specific
    release under a newer version.

(d) Not Legal Advice. This License is a software license, not a legal
    services agreement. The Licensor recommends having it reviewed by
    qualified counsel before relying on it for a public release.

================================================================================
APPENDIX: How to Apply This Dual License
================================================================================

To apply the HyperNix Dual License to a work, attach the following notice,
replacing the bracketed fields with your own identifying information:

    Copyright [yyyy] [name of copyright owner]

    This software is available under your choice of:

      (A) the HyperNix OpenCode Light Limited Use License, Version 0.1
          (LLU-0.1); or

      (B) the HyperNix Open Source License, Version 1.0 (HOS-1.0).

    You must elect one license and comply with its terms. You may not
    combine terms from both licenses.

    You may obtain a copy of both licenses at:

        [URL to this license text]

    Unless required by applicable law or agreed to in writing, software
    distributed under either license is distributed on an "AS IS" BASIS,
    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
    implied. See the applicable License for the specific language
    governing permissions and limitations.
