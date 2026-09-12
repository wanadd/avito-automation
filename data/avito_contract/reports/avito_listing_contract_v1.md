# Avito Listing Contract V1

## AVITO OPENAPI DISCOVERY
FAIL

## AUTOLOAD API SURFACE
| Method | Path | Operation | Lifecycle | Runtime access |
| --- | --- | --- | --- | --- |
| GET | /autoload/v1/accounts/{user_id}/items/{ad_id} |  | LEGACY | AUTH_REQUIRED |
| GET | /autoload/v1/accounts/{user_id}/reports |  | LEGACY | AUTH_REQUIRED |
| GET | /autoload/v1/accounts/{user_id}/reports/last_report |  | LEGACY | AUTH_REQUIRED |
| GET | /autoload/v1/accounts/{user_id}/reports/{reportId} |  | LEGACY | AUTH_REQUIRED |

## CATEGORY TREE DISCOVERY
AUTH_REQUIRED

## CATEGORY FIELD DISCOVERY
AUTH_REQUIRED

## AUTOLOAD FORMAT
DOCUMENTED_TEMPLATE_AVAILABLE

## TITLE RULES
UNKNOWN

## DESCRIPTION RULES
UNKNOWN

## IMAGE RULES
UNKNOWN

## PRICE RULES
Avito payload representation UNKNOWN. Internal pricing engine remains minor integer units.

## DELIVERY FIELDS
UNKNOWN

## LOCATION FIELDS
UNKNOWN

## CONTACT FIELDS
UNKNOWN

## LIFECYCLE CHECK
PASS

## CURRENT AUTOLOAD VERSION DISCOVERY
| Version | Lifecycle | Evidence count |
| --- | --- | --- |
| v1 | LEGACY | 4 |

## LISTING CORE CONTRACT
| Field | Status | Source | Evidence |
| --- | --- | --- | --- |
| Id | UNKNOWN | UNKNOWN |  |
| Category | UNKNOWN | UNKNOWN |  |
| Title | UNKNOWN | UNKNOWN |  |
| Description | UNKNOWN | UNKNOWN |  |
| Price | UNKNOWN | UNKNOWN |  |
| Images | UNKNOWN | UNKNOWN |  |
| Address | UNKNOWN | UNKNOWN |  |
| ContactMethod | UNKNOWN | UNKNOWN |  |
| Condition | UNKNOWN | UNKNOWN |  |
| Delivery | UNKNOWN | UNKNOWN |  |

## AUTH MATRIX
| Operation | Schema | Runtime auth | Paid | Account | Safe |
| --- | --- | --- | --- | --- | --- |
| GET /autoload/v1/accounts/{user_id}/items/{ad_id} | True | True | UNKNOWN | True | False |
| GET /autoload/v1/accounts/{user_id}/reports | True | True | UNKNOWN | True | False |
| GET /autoload/v1/accounts/{user_id}/reports/last_report | True | True | UNKNOWN | True | False |
| GET /autoload/v1/accounts/{user_id}/reports/{reportId} | True | True | UNKNOWN | True | False |
| GET /autoload/v1/user-docs/tree | False | True | UNKNOWN | True | FUTURE |

## ELECTRONICS CATEGORY MAPPING
See avito_electronics_mapping.md.

## CONTRACT COVERAGE
- total_discovered_fields: 0
- confirmed_fields: 0
- strong_fields: 0
- partial_fields: 0
- unknown_fields: 0
- auth_locked_fields: 0
- enum_fields_with_values: 0
- enum_fields_without_values: 0
- required_fields_confirmed: 0
- required_fields_unknown: 0

## CONTRACT GAPS
See avito_contract_gaps.md.

## SOURCES
| Source | Type | Status | Access | SHA256 |
| --- | --- | --- | --- | --- |
| https://developers.avito.ru/openapi.json | OFFICIAL_OPENAPI | 404 | UNKNOWN |  |
| https://developers.avito.ru/api/openapi.json | OFFICIAL_OPENAPI | 404 | UNKNOWN |  |
| https://api.avito.ru/openapi.json | OFFICIAL_OPENAPI | 404 | UNKNOWN |  |
| https://api.avito.ru/swagger.json | OFFICIAL_OPENAPI | 404 | UNKNOWN |  |
| https://developers.avito.ru/api-catalog | OFFICIAL_DOCS | 200 | PUBLIC | 80c35ff7e1c8cf5aa9d02499453c672676a0de82ea3d4f5abaa2f1230027ecd7 |
| https://www.avito.ru/autoload/documentation | OFFICIAL_DOCS | 200 | PUBLIC | 0326bbbce73014467e9418b27057ff3c05b403ae05f6dd0631ae8fa475874bce |
| https://www.avito.ru/autoload/documentation/templates | OFFICIAL_TEMPLATE | 200 | PUBLIC | 606545697fe233129f8fd5cb9bd86a1047cb78721d7f2f8c7a7dedffa79b3309 |
| https://apis.io/ | PUBLIC_API_MIRROR | 200 | PUBLIC | 8723ac0d096d9fd6e85416c0e6057a87df0506b0185c06d8c840e1dda452b6c6 |
| https://raw.githubusercontent.com/covox/avito_api/master/docs/Api/AutoloadApi.md | PUBLIC_API_MIRROR | 200 | PUBLIC | 4b9fc56678b2f5b4d5f00af210471d1657be4bc7204394dc4d53a8be7b9df041 |
| https://www.avito.ru/autoload/documentation/templates/115710 | OFFICIAL_TEMPLATE | 429 | UNKNOWN |  |
| https://www.avito.ru/autoload/documentation/templates/116608 | OFFICIAL_TEMPLATE | 429 | UNKNOWN |  |
| https://www.avito.ru/autoload/documentation/templates/123374 | OFFICIAL_TEMPLATE | 429 | UNKNOWN |  |
| https://www.avito.ru/autoload/documentation/templates/150400 | OFFICIAL_TEMPLATE | 429 | UNKNOWN |  |
| https://www.avito.ru/autoload/documentation/templates/66863 | OFFICIAL_TEMPLATE | 429 | UNKNOWN |  |
| https://www.avito.ru/autoload/documentation/templates/66906 | OFFICIAL_TEMPLATE | 429 | UNKNOWN |  |
| https://www.avito.ru/autoload/documentation/templates/66925 | OFFICIAL_TEMPLATE | 429 | UNKNOWN |  |
| https://www.avito.ru/autoload/documentation/templates/71631 | OFFICIAL_TEMPLATE | 429 | UNKNOWN |  |
| https://www.avito.ru/autoload/documentation/templates/77216 | OFFICIAL_TEMPLATE | 429 | UNKNOWN |  |
| https://www.avito.ru/autoload/documentation/templates/77217 | OFFICIAL_TEMPLATE | 429 | UNKNOWN |  |
| https://www.avito.ru/autoload/documentation/templates/77218 | OFFICIAL_TEMPLATE | 429 | UNKNOWN |  |
| https://www.avito.ru/autoload/documentation/templates/77219 | OFFICIAL_TEMPLATE | 429 | UNKNOWN |  |
| https://www.avito.ru/autoload/documentation/templates/77324 | OFFICIAL_TEMPLATE | 429 | UNKNOWN |  |
| https://www.avito.ru/autoload/documentation/templates/77326 | OFFICIAL_TEMPLATE | 429 | UNKNOWN |  |
| https://www.avito.ru/autoload/documentation/templates/77327 | OFFICIAL_TEMPLATE | 429 | UNKNOWN |  |
| https://www.avito.ru/developers/api-catalog | PUBLIC_FRONTEND_CONTRACT | 429 | UNKNOWN |  |
| https://www.avito.ru/developers/api-catalog" | PUBLIC_FRONTEND_CONTRACT | 404 | UNKNOWN |  |
| https://www.avito.ru/static/autoload-frontend/assets/c1c9a39d5dfab2c0.svg | PUBLIC_FRONTEND_CONTRACT | 200 | PUBLIC | 34934c518d636ae5ea4dec76ef56a72e84eb74ced4164ceecd06f0815900aee6 |
| https://www.avito.ru/static/autoload-frontend/client/Documentation.e7728d06cd46d938.css | PUBLIC_FRONTEND_CONTRACT | 200 | PUBLIC | c64cb38da0d595c4f758b17dc234f22f94439e9a1f31ed83dd1954108b084b0c |
| https://www.avito.ru/static/autoload-frontend/client/Documentation.e8eb47e27a5e1560.js | PUBLIC_FRONTEND_CONTRACT | 200 | PUBLIC | 8cae0ecc999e81263db35f3faf53781a995ee316edfb3ceb09808e5bfe9fa11f |
| https://www.avito.ru/static/autoload-frontend/client/remoteEntry.ad6d466143f64590.js | PUBLIC_FRONTEND_CONTRACT | 200 | PUBLIC | bbe1c84ece45066bcbb249cdcacb96a13790bb21242c902e172066a981b5b1db |
| https://www.avito.st/s/autoload/getting-started/close-all-items.mp4 | PUBLIC_FRONTEND_CONTRACT | 200 | PUBLIC | c00576ec22d7a85d6c68d7b6e7dad5f9ec625f7d353df2024484ebcba3ea276a |
| https://www.avito.st/s/autoload/getting-started/create-item.mp4 | PUBLIC_FRONTEND_CONTRACT | 200 | PUBLIC | 1a5686590e23bc1dda978bc6fe300832c0e8b85c8d4972fe5c238f8b960fc34c |
| https://www.avito.st/s/autoload/getting-started/download-template.mp4 | PUBLIC_FRONTEND_CONTRACT | 200 | PUBLIC | 751efcce0c49fee98b6501c353aa577a1c9b0d8aa14a5b1459d4605f29ed08f4 |
| https://www.avito.st/s/autoload/getting-started/edit-item.mp4 | PUBLIC_FRONTEND_CONTRACT | 200 | PUBLIC | c1d70d4a1a94a63cb3da0432bac1060d3507fea3cc4faaafe39ea685e9f6fe6b |
| https://www.avito.st/s/autoload/getting-started/photo-by-files.mp4 | PUBLIC_FRONTEND_CONTRACT | 200 | PUBLIC | 1ad88b9bc161e295c4a067519253b78f060867009be02d211213851244a3647b |
| https://www.avito.st/s/autoload/getting-started/photo-by-urls.mp4 | PUBLIC_FRONTEND_CONTRACT | 200 | PUBLIC | 679cbcc540af9fc43e5b27cf9dfcb9e46ef15bba97ac4055b8f2d66cecd96e5f |
| https://www.avito.st/s/autoload/getting-started/template-overview.mp4 | PUBLIC_FRONTEND_CONTRACT | 200 | PUBLIC | e5e9c9e8841d69810398dc53b691e6273405deca7427f71cf6262ff6f1b7d29b |
| https://www.avito.st/s/autoload/redesign-docs/how-to-open-last-report.mp4 | PUBLIC_FRONTEND_CONTRACT | 200 | PUBLIC | d1589adb79d7281ff18c0d993aff56a5c3fb26d837e6d87eabdec7732b361ac6 |
| https://www.avito.st/s/autoload/redesign-docs/how-to-open-reports-history.mp4 | PUBLIC_FRONTEND_CONTRACT | 200 | PUBLIC | f3225192517048f4495e285c895f05ecf80668a8a73dbef2d44274a39598d81b |

## SPRINT 0.9 READINESS
SPRINT 0.9 GENERIC CONTENT ENGINE READINESS: PASS_WITH_LIMITATIONS
SPRINT 0.9 AVITO LISTING ADAPTER READINESS: FAIL
AVITO LISTING CONTRACT GATE: FAIL
AVITO PUBLIC RESEARCH: PASS_WITH_LIMITATIONS

## SECURITY CHECK
No credentials, cookies, sessions, tokens, or API mutations are used by this harvester.

## FINAL MARKERS
HARVESTER IMPLEMENTATION: PASS
PUBLIC TEMPLATE ASSET DISCOVERY: PASS_WITH_LIMITATIONS
PUBLIC NETWORK CONTRACT DISCOVERY: PASS_WITH_LIMITATIONS
CURRENT AUTOLOAD VERSION DISCOVERY: FAIL
LISTING CORE CONTRACT: FAIL
CATEGORY FIELD CONTRACT: AUTH_REQUIRED
TITLE/DESCRIPTION CONTRACT: UNKNOWN
IMAGE CONTRACT: UNKNOWN
PRICE CONTRACT: UNKNOWN
ELECTRONICS CATEGORY MAPPING: PASS_WITH_LIMITATIONS
CONTRACT CONFLICT CHECK: PASS
OFFLINE REPRODUCIBILITY: PASS
SECURITY CHECK: PASS
AVITO OPENAPI DISCOVERY: FAIL
AUTOLOAD API SURFACE: PASS
CATEGORY TREE DISCOVERY: AUTH_REQUIRED
CATEGORY FIELD DISCOVERY: AUTH_REQUIRED
AUTOLOAD PAYLOAD CONTRACT: PASS_WITH_LIMITATIONS
TITLE/DESCRIPTION RULES: UNKNOWN
LIFECYCLE CHECK: PASS
AUTH MATRIX: PASS
ELECTRONICS MAPPING: PASS_WITH_LIMITATIONS
CONTRACT COVERAGE: FAIL
AVITO LISTING CONTRACT GATE: FAIL
