version: "2025.v1.0.cn"
meta:
  persona: "CR_ProInternAuditor"
  description: "V1: 工程级AI代码评审规则集。结构化、全面、深度原则化、专业、可落地。"
  version_ruleset: "2025.v1.0.cn"
  schema_info:
    rules_schema_url: "./schemas/rules.schema.json"
    issue_schema_url: "./schemas/issue.schema.json"
  changelog_url: "./CHANGELOG.md"
  rule_sources_notes: # 描述预期的模块化结构 (实际输出为合并版)
    - "核心原则: ./rules/common_FND.yml"
    - "设计模式: ./rules/common_DSN.yml"
    - "实现质量: ./rules/common_IMP.yml"
    - "安全基础: ./rules/common_SEC.yml"
    - "并发异步: ./rules/common_CNC.yml"
    - "测试正确: ./rules/common_TST.yml"
    - "性能效率: ./rules/common_PRF.yml"
    - "维护演进: ./rules/common_MNT.yml"
    - "工程常识: ./rules/common_CSH.yml"
    - "Java规则: ./rules/lang/java.yml"
    - "Python规则: ./rules/lang/python.yml"
    - "JS/TS规则: ./rules/lang/js_ts.yml"
    - "Go规则: ./rules/lang/go.yml"
    - "C++规则: ./rules/lang/cpp.yml"
    - "C#规则: ./rules/lang/csharp.yml"
    - "Ruby规则: ./rules/lang/ruby.yml"
    - "Rust规则: ./rules/lang/rust.yml"

  target_audience_notes_for_ai:
    - "目标: 聪明但缺乏实战经验的开发者。"
    - "关注: 基础原理应用、常见工程陷阱、NFR疏忽、理论与实践差距。"
    - "反馈: 专业、建设性、教育性。基于单条规则的'rat'字段内涵，并结合代码上下文，深入解释'为什么这么要求以及违反的后果'，必要时给出修复建议或引导思考方向。"
    - "核心: 提升代码质量与开发者工程素养。"

  legend: # --- 图例 ---
    lvl: {M: 必须, S: 应当, A: 避免}
    sev: {B: 阻塞, C: 关键, H: 高危, M: 中危, L: 低危}
    cat: {
      FND: 基础原则, DSN: 设计模式与反模式, IMP: 实现质量,
      SEC: 安全基础, CNC: 并发与异步, TST: 可测试性与正确性,
      PRF: 性能感知, MNT: 可维护性与演进, CSH: 工程常识启发,
      RSRC: 资源管理与生命周期 # 已添加
    }
    act: {
      RQR: 要求重构, RCM: 推荐重构, FIX: 可自动修复,
      CNF: 要求确认意图, EDU: 解释与教育, LOG: 记录技术债,
      WARN: 警告关注 # 已添加
    }
    state: {P: 生产可用, T: 试验中, E: 实验性待评估, D: 已弃用}

  tool_registry: # --- 工具注册表 ---
    aih: "AI Helper (LLM-based Analysis)"
    lzd: "Lizard (Code Metrics)"
    sg: "Semgrep (Pattern Matching)"
    spb: "SpotBugs (Java Analysis)"
    pmd: "PMD (Multi-language Analysis)"
    rfk: "Ruff (Python Linter)"
    esl: "ESLint (JS/TS Linter)"
    sa: "Static Analyzer (Generic/Specific)"
    git: "Git History Analyzer"
    tst: "Test Analysis Proxy"
    prf: "Profiler Proxy"
    man: "Manual Review Indicator"
    sq: "SonarQube Proxy"
    pylint: "Pylint (Python Linter)"
    cppcheck: "Cppcheck (C/C++ Analysis)"
    clang-tidy: "Clang-Tidy (C++ Analysis)"
    roslyn: "Roslyn Analyzer (C# Analysis)"
    rubocop: "RuboCop (Ruby Linter)"
    rustc: "Rust Compiler/Clippy"

rules:
  ## --- FND: 软件基本原则 ---
  - {id: FND_001, lvl: M, sev: C, cat: FND, lang: "*", state: P, met: {type: metric_comparison, expr: {fn: "calculate_srp_violation_score", params: {unit: "current_code_unit"}}, operator: ">", threshold: 0.7, unit: "score"}, det: [{tool: aih, rule: "srp_cohesion_analysis"}, {tool: lzd, rule: "unit_metrics_proxy"}], act: RQR, rat: "职责单一性不足 -> 维护性降低 测试性降低 逻辑边界模糊 ; #单一职责原则 #关注点分离"}
  - {id: FND_002, lvl: M, sev: H, cat: FND, lang: "*", state: P, met: {type: duplication_check, expr: {min_lines: 5, similarity_threshold: 0.85}, cfg_key: "DRY_SIMILARITY_THRESHOLD"}, det: [{tool: sg, rule: "semantic_clone_detection"}, {tool: aih, rule: "block_similarity"}], act: FIX, autofix: {type: "ai_patch", prompt_template: "Refactor duplicated code block {{code_snippet}} into a shared function/method."}, rat: "代码重复 -> 缺陷易传播 更新不一致 维护成本剧增 ; #DRY原则 #代码复用"}
  - {id: FND_003, lvl: M, sev: H, cat: FND, lang: "*", state: P, met: {type: heuristic_check, expr: {fn: "evaluate_solution_to_problem_complexity_mismatch_ratio"}, operator: ">", threshold: 1.5}, det: [{tool: aih, rule: "overengineering_pattern_detection"}, {tool: man, confidence: 0.5}], act: RCM, rat: "过度复杂化 -> 认知负荷高 调试困难 开发效率低 ; #KISS原则 #过度设计"}
  - {id: FND_004, lvl: S, sev: M, cat: FND, lang: "*", state: P, met: {type: code_usage_analysis, expr: {scope: "public_api_or_logic", usage_expected: true, actual_usage_found: false}}, det: [{tool: aih, rule: "dead_code_path_analysis"}, {tool: git, rule: "commit_scope_vs_code_usage"}], act: EDU, rat: "预测性编码 -> 系统臃肿 维护分散注意力 ; #YAGNI原则 #需求驱动"}
  - {id: FND_005, lvl: M, sev: C, cat: FND, lang: "*", state: P, met: {type: state_mutability_check, expr: {is_shared: true, is_mutable: true, is_protected_by_sync: false}}, det: [{tool: spb, rule: "MS_SHOULD_BE_FINAL_OR_SYNC_ACCESS"}, {tool: aih, rule: "shared_mutability_dataflow"}], act: RQR, rat: "共享可变状态无保护 -> 并发风险 数据竞争 状态不可预测 ; #不可变性 #线程安全"}
  - {id: FND_006, lvl: M, sev: H, cat: FND, lang: "*", state: P, met: {type: api_contract_check, expr: {clarity_score_threshold: 0.6, completeness_check: true, consistency_check_with_impl: true}}, det: [{tool: aih, rule: "doc_completeness_accuracy_vs_signature_usage"}, {tool: sg, rule: "api_param_return_validation_missing_pattern"}], act: RQR, rat: "API契约模糊 -> 调用端误用 集成失败 调试困难 ; #API设计 #接口契约"}
  - {id: FND_007, lvl: M, sev: H, cat: FND, lang: "*", state: P, met: {type: algo_complexity_check, expr: {path_type: "critical_hotpath", complexity_allowed: "O_N_log_N_or_better", actual_complexity_detected: "O_N_squared_or_worse"}}, det: [{tool: prf, rule: "loop_data_access_pattern_analysis"}, {tool: aih, rule: "ds_choice_vs_ops_complexity_mismatch"}], act: RCM, rat: "算法低效 -> 性能瓶颈 伸缩性受限 资源耗尽 ; #性能考量 #算法选择"}
  - {id: FND_008, lvl: M, sev: C, cat: FND, lang: "*", state: P, met: {type: ocp_violation_check, expr: {modification_for_new_behavior: true, extension_points_used: false}}, det: [{tool: git, rule: "churn_on_stable_modules_for_feature_add"}, {tool: aih, rule: "missing_extension_points_abstraction_level_check"}], act: RCM, rat: "开闭原则违背 -> 回归风险高 扩展性差 ; #开闭原则 #代码扩展性"}
  - {id: FND_009, lvl: M, sev: H, cat: FND, lang: "*", state: P, met: {type: lsp_violation_check, expr: {subtype_behavior_consistent_with_base: false}}, det: [{tool: aih, rule: "override_method_pre_post_condition_invariants_semantic_diff"}, {tool: tst, rule: "subtype_substitution_test_failures_analysis"}], act: RQR, rat: "里氏替换违背 -> 多态性被破坏 行为意外 继承体系混乱 ; #里氏替换原则 #继承正确性"}
  - {id: FND_010, lvl: S, sev: M, cat: FND, lang: "*", state: P, met: {type: isp_violation_check, expr: {interface_is_fat: true, client_uses_subset_only: true}}, det: [{tool: aih, rule: "interface_client_method_usage_matrix_analysis"}, {tool: sa, rule: "interface_cohesion_metrics_lcomi_like"}], act: RCM, rat: "接口隔离违背 -> 不必要耦合 变更影响范围广 ; #接口隔离原则 #接口设计"}
  - {id: FND_011, lvl: M, sev: H, cat: FND, lang: "*", state: P, met: {type: dip_violation_check, expr: {high_level_depends_on_concrete_low_level: true}}, det: [{tool: sa, rule: "dependency_direction_analysis_abstraction_usage_count"}, {tool: aih, rule: "di_framework_misconfiguration_or_manual_concrete_instantiation"}], act: RQR, rat: "依赖倒置违背 -> 系统僵化 难于替换实现 测试性降低 ; #依赖倒置原则 #解耦设计"}

  ## --- DSN: 设计模式与反模式 ---
  - {id: DSN_001, lvl: S, sev: M, cat: DSN, lang: "*", state: P, met: {type: pattern_application_check, expr: {pattern_name: "any_gof_or_enterprise_pattern", problem_fit_score: "<0.5"}}, det: [{tool: aih, rule: "gof_pattern_signature_detection_vs_problem_description_semantic_fit"}, {tool: man, confidence: 0.6}], act: EDU, rat: "模式误用或滥用 -> 不必要复杂性 维护成本增加 代码清晰度降低 ; #设计模式应用 #避免过度设计"}
  - {id: DSN_002, lvl: M, sev: H, cat: DSN, lang: "*", state: P, met: {type: anti_pattern_metric, expr: {name: "god_object_or_method", lcom_score: "<0.3", cbo_score: ">10", method_count: ">20"}}, det: [{tool: lzd, rule: "class_method_combined_metrics_thresholds"}, {tool: sq, rule: "god_class_sonarqube_rules"}], act: RQR, rat: "神对象或神方法 -> 严重违反单一职责 系统脆弱点 极难测试和维护 ; #反模式识别 #SRP极端违反"}
  - {id: DSN_003, lvl: A, sev: M, cat: DSN, lang: "*", state: P, met: {type: anti_pattern_check, expr: {name: "global_state_or_singleton", justification_present_and_valid: false}}, det: [{tool: sa, rule: "global_variable_modification_points_scan"}, {tool: aih, rule: "singleton_necessity_and_testability_impact_analysis"}], act: RCM, rat: "全局状态或单例滥用 -> 隐式依赖 测试污染 并发风险增加 ; #反模式识别 #全局状态陷阱"}
  - {id: DSN_004, lvl: S, sev: M, cat: DSN, lang: "*", state: P, met: {type: creational_pattern_opportunity, expr: {object_creation_complexity: "high", constructor_params_count: ">5"}, cfg_key: "MAX_PARAMS_NO_BUILDER_X3"}, det: [{tool: sa, rule: "constructor_parameter_count_analysis"}, {tool: aih, rule: "instantiation_logic_repetition_and_complexity_score"}], act: RCM, rat: "复杂对象创建逻辑散乱 -> 构造过程脆弱 API不清晰 违反开闭原则 ; #创建型模式 #Builder模式 #Factory模式"}
  - {id: DSN_005, lvl: M, sev: H, cat: DSN, lang: "*", state: P, met: {type: structural_principle_violation, expr: {name: "law_of_demeter", call_chain_depth: ">3", foreign_object_interaction: true}}, det: [{tool: aih, rule: "method_call_chain_object_origin_and_depth_analysis"}, {tool: sa, rule: "accessor_chain_length_detection"}], act: RCM, rat: "迪米特法则违背 -> 高耦合 信息泄露 修改易引发连锁反应 ; #迪米特法则 #松耦合"}
  - {id: DSN_006, lvl: A, sev: M, cat: DSN, lang: "*", state: P, met: {type: anti_pattern_check, expr: {name: "anemic_domain_model", data_class_behavior_ratio: "<0.2"}}, det: [{tool: aih, rule: "class_methods_vs_fields_and_setters_getters_analysis"}, {tool: man, confidence: 0.7}], act: EDU, rat: "贫血领域模型 -> 面向过程设计 对象职责缺失 领域逻辑分散 ; #DDD #面向对象设计 #贫血模型反模式"}
  - {id: DSN_007, lvl: S, sev: M, cat: DSN, lang: "*", state: P, met: {type: behavioral_pattern_opportunity, expr: {name: "null_object_pattern", frequent_null_checks_for_dependency: true, null_represents_valid_no_op_state: true}}, det: [{tool: aih, rule: "null_check_frequency_and_conditional_logic_complexity_analysis"}, {tool: sa, rule: "optional_return_type_usage_analysis"}], act: RCM, rat: "过多空值检查 -> 代码冗余 逻辑分支复杂 易遗漏空指针 ; #NullObject模式 #代码简洁性"}
  - {id: DSN_008, lvl: M, sev: H, cat: DSN, lang: "*", state: P, met: {type: anti_pattern_check, expr: {name: "spaghetti_code", control_flow_complexity_score: ">0.8", lack_of_clear_structure: true}}, det: [{tool: aih, rule: "control_flow_graph_analysis_for_tangles_and_high_cyclomatic_complexity_without_structure"}, {tool: lzd, rule: "high_cc_and_low_modularity_metrics"}], act: RQR, rat: "面条代码 -> 逻辑混乱难以追踪 控制流复杂 维护和调试极为困难 ; #反模式识别 #代码结构"}
  - {id: DSN_009, lvl: A, sev: M, cat: DSN, lang: "*", state: P, met: {type: anti_pattern_check, expr: {name: "lava_flow_dead_or_obsolete_code_retained"}}, det: [{tool: git, rule: "code_age_analysis_vs_last_commit_author_activity"}, {tool: aih, rule: "heuristic_for_potentially_obsolete_code_blocks_or_features_with_no_clear_usage"}], act: CNF, rat: "熔岩流(保留无用代码) -> 代码库膨胀 增加理解和维护成本 隐藏风险 ; #反模式识别 #代码清理"}
  - {id: DSN_010, lvl: S, sev: M, cat: DSN, lang: "*", state: P, met: {type: pattern_choice_opportunity, expr: {fixed_algorithm_structure_with_variant_steps: true, inheritance_used_for_variation: true, composition_preferred_for_flexibility: "maybe"}}, det: [{tool: aih, rule: "analysis_of_inheritance_hierarchy_for_algorithm_step_overrides_vs_strategy_pattern_applicability"}], act: EDU, rat: "算法步骤固定但实现可变 -> 策略模式可能优于模板方法 提升灵活性 ; #设计模式选择 #继承与组合"}

  ## --- IMP: 实现质量与可读性 ---
  - {id: IMP_001, lvl: M, sev: H, cat: IMP, lang: "*", state: P, met: {type: naming_convention_check, expr: {style_guide_adherence_score: "<0.9", semantic_clarity_score: "<0.8", generic_name_percentage: ">0.1"}}, det: [{tool: aih, rule: "identifier_semantic_clarity_token_analysis_and_standard_naming_pattern_matching"}, {tool: rfk, rule: "naming_rules_error_count"}], act: RCM, rat: "命名规范差 -> 代码难以理解 易产生误解 调试维护耗时 ; #可读性 #命名即文档"}
  - {id: IMP_002, lvl: M, sev: C, cat: IMP, lang: "*", state: P, met: {type: error_handling_check, expr: {empty_catch_blocks_found: true, or_swallowed_exceptions_without_logging_or_rethrow: true, or_loss_of_original_error_context: true}}, det: [{tool: spb, rule: "REC_EMPTY_CATCH_BLOCK_OR_EXCEPTION_SWALLOWED"}, {tool: sg, rule: "lang_specific_empty_or_trivial_catch_block_detection"}], act: RQR, rat: "错误处理不当 -> 静默失败 数据丢失或损坏 级联问题 调试噩梦 ; #健壮性 #异常处理最佳实践"}
  - {id: IMP_003, lvl: M, sev: C, cat: RSRC, lang: "*", state: P, met: {type: resource_management_check, expr: {resource_type_pattern: "(File|Socket|Connection|Stream|Cursor|Lock)", not_closed_in_finally_or_try_with_resources: true}}, det: [{tool: spb, rule: "OS_OPEN_STREAM_MUST_BE_CLOSED"}, {tool: pmd, rule: "CloseResource"}], act: RQR, rat: "资源泄露 -> 系统稳定性降低 性能下降 最终可能崩溃 ; #资源管理 #RAII #try_with_resources"}
  - {id: IMP_004, lvl: M, sev: M, cat: IMP, lang: "*", state: P, met: {type: magic_value_check, expr: {unexplained_literal_found: true, not_in_constant_definition: true, literal_type_pattern: "(numeric|string|boolean)"}}, det: [{tool: sa, rule: "literal_value_scan_for_non_trivial_values_outside_of_constant_definitions_or_allowlist"}, {tool: aih, rule: "heuristic_for_magic_number_or_string_candidates_based_on_context"}], act: FIX, autofix: {type: "ai_patch", prompt_template: "Refactor magic value {{violated_value}} into a named constant in {{code_snippet}}."}, rat: "魔法值硬编码 -> 代码晦涩难懂 维护时易引入新错误 配置管理困难 ; #可读性 #可维护性"}
  - {id: IMP_005, lvl: S, sev: L, cat: IMP, lang: "*", state: P, met: {type: comment_quality_check, expr: {comment_staleness_score: ">0.5", or_comment_explains_what_not_why: true, or_obvious_code_commented: true}}, det: [{tool: aih, rule: "comment_to_code_semantic_similarity_and_staleness_detection_using_git_history"}, {tool: git, rule: "blame_analysis_for_comment_age_vs_code_age_and_author_mismatch"}], act: FIX, autofix: {type: "manual_assist", instruction: "Review or remove outdated/obvious comment near {{code_snippet}}."}, rat: "注释质量低 -> 误导开发者 浪费排错时间 降低代码可信度 ; #代码文档化 #有效注释"}
  - {id: IMP_006, lvl: M, sev: L, cat: IMP, lang: "*", state: P, met: {type: formatting_consistency_check, expr: {linter_formatter_violations_found: true}}, det: [{tool: sa, rule: "linter_tool_autoformatter_diff_check"}], act: FIX, autofix: {type: "tool_command", command: "Run configured linter/formatter (e.g., `prettier --write`, `ruff format`)"}, rat: "代码格式不一致 -> 阅读体验降低 增加认知摩擦 代码评审效率降低 ; #代码风格 #团队规范"}
  - {id: IMP_007, lvl: M, sev: H, cat: IMP, lang: "*", state: P, met: {type: cognitive_complexity_check, expr: {cognitive_complexity_score: ">15", or_combined_score_loc_nesting_params: ">Y"}, cfg_key: "MAX_COGNITIVE_SCORE_IMP_X3"}, det: [{tool: sq, rule: "cognitive_complexity_metric_value"}, {tool: lzd, rule: "cyclomatic_complexity_loc_param_count_combined_heuristic_value"}], act: RCM, rat: "复杂逻辑可读性差 -> 难以理解和维护 缺陷高发区域 重构难度大 ; #代码复杂度 #可读性优先"}
  - {id: IMP_008, lvl: M, sev: M, cat: IMP, lang: "*", state: P, met: {type: parameter_design_check, expr: {boolean_flag_parameter_present: true}}, det: [{tool: aih, rule: "function_signature_analysis_for_boolean_flag_parameters"}], act: RCM, rat: "布尔标志参数 -> 函数职责不单一 违反SRP 调用接口不清晰 ; #函数设计 #代码清晰度"}
  - {id: IMP_009, lvl: S, sev: M, cat: IMP, lang: "*", state: P, met: {type: side_effect_check, expr: {unexpected_or_hidden_side_effects_in_query_like_function: true}}, det: [{tool: aih, rule: "command_query_separation_violation_analysis"}, {tool: man, confidence: 0.6}], act: RCM, rat: "函数副作用不明 -> 代码行为难以预测 测试困难 调试复杂 ; #函数式编程思想 #CQS原则"}
  - {id: IMP_010, lvl: M, sev: M, cat: IMP, lang: "*", state: P, met: {type: logging_practice_check, expr: {ineffective_logging_score: ">0.6"}}, det: [{tool: aih, rule: "log_statement_analysis_for_level_context_pii_leak_patterns"}, {tool: sa, rule: "linter_rules_for_logging_best_practices"}], act: RCM, rat: "日志实践不当 -> 诊断困难 性能问题 日志泛滥或信息不足 ; #日志规范 #可观测性"}
  - {id: IMP_011, lvl: S, sev: L, cat: IMP, lang: "*", state: P, met: {type: naming_semantic_check, expr: {name_matches_generic_placeholder_pattern: "(foo|bar|baz|temp|data|info|obj|val|item|stuff|util|manager|helper|handler|process|flag)"}}, det: [{tool: sa, rule: "identifier_token_matching_against_placeholder_and_generic_name_patterns"}], act: RCM, rat: "使用无意义占位符或泛化命名 -> 代码意图模糊 降低可读性 ; #命名质量 #专业表达"}
  - {id: IMP_012, lvl: M, sev: M, cat: IMP, lang: "*", state: P, met: {type: call_chain_check, expr: {method_call_chain_depth: ">4", on_multiple_object_types: true}}, det: [{tool: sa, rule: "static_ast_method_call_chain_depth_and_receiver_variance"}], act: RCM, rat: "方法调用链过长(火车残骸) -> 违反迪米特法则 耦合性高 难以mock和测试 ; #代码结构 #松耦合"}
  - {id: IMP_013, lvl: A, sev: M, cat: MNT, lang: "*", state: P, met: {type: todo_comment_check, expr: {todo_comment_found: true, missing_ticket_id_or_author_or_date: true}}, det: [{tool: sa, rule: "regex_scan_for_TODO_FIXME_XXX_comments_without_tracking_info"}], act: WARN, rat: "TODO注释缺乏追踪 -> 技术债易被遗忘 代码质量逐渐腐化 ; #技术债管理 #代码注释规范"} # Changed act to WARN, cat to MNT

  ## --- SEC: 安全基础 ---
  - {id: SEC_001, lvl: M, sev: H, cat: SEC, lang: "*", state: P, met: {type: owasp_top10_id, expr: {name: "A01_2021_BrokenAccessControl"}}, det: [{tool: aih, rule: "access_control_pattern_analysis"}, {tool: sg, rule: "access_control_vulnerability_patterns"}], act: RQR, rat: "访问控制失效 -> 未授权用户可能访问敏感数据或执行特权操作 ; #OWASP #访问控制"}
  - {id: SEC_002, lvl: M, sev: H, cat: SEC, lang: "*", state: P, met: {type: owasp_top10_id, expr: {name: "A03_2021_Injection"}}, det: [{tool: sg, rule: "sql_injection_sinks_or_xss_patterns"}, {tool: aih, rule: "taint_analysis_for_injection_flows"}], act: RQR, rat: "注入漏洞(SQL/XSS/Cmd) -> 执行任意代码 窃取数据 破坏系统 ; #OWASP #注入防范"}
  - {id: SEC_003, lvl: M, sev: C, cat: SEC, lang: "*", state: P, met: {type: owasp_top10_id, expr: {name: "A02_2021_CryptographicFailures"}}, det: [{tool: aih, rule: "weak_crypto_algo_or_key_management_usage"}, {tool: sg, rule: "hardcoded_secrets_or_weak_hashing_functions"}], act: RQR, rat: "加密失败 -> 敏感数据泄露 用户凭证被盗 违反合规性 ; #OWASP #加密安全"}
  - {id: SEC_011, lvl: M, sev: C, cat: SEC, lang: "*", state: P, met: {type: crypto_weakness, expr: {use_of_non_cryptographically_secure_random_number_generator_for_security_sensitive_ops: true}}, det: [{tool: sg, rule: "lang_insecure_randomness_pattern_match"}, {tool: aih, rule: "contextual_analysis_of_random_number_usage_for_security_implications"}], act: RQR, rat: "使用不安全随机数 -> 敏感信息(如令牌)易被预测 导致安全漏洞 ; #密码学安全 #随机数生成"}
  - {id: SEC_012, lvl: M, sev: H, cat: SEC, lang: "*", state: P, met: {type: owasp_top10_id, expr: {name: "A05_2021_XXE", condition: "xml_parser_allows_external_entities"}}, det: [{tool: sg, rule: "lang_xxe_vulnerable_xml_parser_configuration"}, {tool: sa, rule: "dependency_check_for_known_vulnerable_xml_parsers"}], act: RQR, rat: "XML外部实体注入(XXE) -> 可导致信息泄露 SSRF DoS ; #OWASP安全风险 #XML安全"}
  - {id: SEC_013, lvl: M, sev: C, cat: SEC, lang: "*", state: P, met: {type: owasp_top10_id, expr: {name: "A08_2021_InsecureDeserialization"}}, det: [{tool: sg, rule: "lang_insecure_deserialization_patterns"}, {tool: aih, rule: "analysis_of_data_sources_for_deserialization_and_trust_boundaries"}], act: RQR, rat: "不安全的反序列化 -> 可导致远程代码执行 DoS 数据篡改 ; #OWASP安全风险 #数据完整性"}

  ## --- CNC: 并发与异步编程 ---
  - {id: CNC_001, lvl: M, sev: H, cat: CNC, lang: "*", state: P, met: {type: concurrency_issue, expr: {name: "race_condition_potential"}}, det: [{tool: aih, rule: "race_condition_heuristic_analysis"}, {tool: sa, rule: "thread_safety_analyzer_rules"}], act: RQR, rat: "潜在竞争条件 -> 数据不一致 程序崩溃 结果不可预测 ; #并发编程 #竞争条件"}
  - {id: CNC_002, lvl: M, sev: H, cat: CNC, lang: "*", state: P, met: {type: concurrency_issue, expr: {name: "deadlock_potential"}}, det: [{tool: aih, rule: "lock_ordering_and_dependency_graph_analysis"}, {tool: sa, rule: "deadlock_detection_patterns"}], act: RQR, rat: "潜在死锁 -> 系统无响应 资源无法释放 ; #并发编程 #死锁"}
  - {id: CNC_007, lvl: M, sev: H, cat: CNC, lang: "java", state: P, met: {type: keyword_misuse, expr: {name: "java_synchronized_misuse", detail: "sync_on_non_final_or_this_or_string_or_boxed"}}, det: [{tool: spb, rule: "DL_SYNCHRONIZATION_ON_NON_FINAL_FIELD_OR_SHARED_CONSTANT"}], act: RCM, rat: "Synchronized关键字误用 -> 可能导致死锁或未能正确保护共享资源 ; #Java并发 #同步机制"}
  - {id: CNC_008, lvl: M, sev: M, cat: CNC, lang: "go", state: P, met: {type: pattern_id, expr: {name: "go_unbuffered_channel_misuse", detail: "rw_without_concurrent_pair"}}, det: [{tool: aih, rule: "go_channel_usage_pattern_analysis_for_blocking"}, {tool: sa, rule: "golangci_lint_deadlock_detection"}], act: RCM, rat: "Go无缓冲Channel使用不当 -> Goroutine永久阻塞导致泄露或死锁 ; #Go并发模式 #Channel通信"}

  ## --- TST: 可测试性与代码正确性 ---
  - {id: TST_001, lvl: S, sev: M, cat: TST, lang: "*", state: P, met: {type: test_coverage_gap, expr: {critical_logic_path_coverage_below_threshold: 0.8}, cfg_key: "MIN_CRITICAL_COVERAGE"}, det: [{tool: tst, rule: "coverage_report_critical_path_analysis"}, {tool: aih, rule: "identify_untested_critical_logic"}], act: LOG, rat: "关键逻辑测试覆盖不足 -> 回归风险高 缺陷易逃逸 ; #测试覆盖率 #代码质量"}
  - {id: TST_002, lvl: M, sev: M, cat: TST, lang: "*", state: P, met: {type: test_design_flaw, expr: {hardcoded_dependencies_in_unit_tests: true}}, det: [{tool: aih, rule: "dependency_injection_mocking_pattern_analysis_in_tests"}, {tool: sa, rule: "static_instantiation_in_tests"}], act: RCM, rat: "单元测试硬编码依赖 -> 测试脆弱 难以隔离被测单元 ; #可测试性 #依赖注入 #Mocking"}
  - {id: TST_007, lvl: S, sev: M, cat: TST, lang: "*", state: P, met: {type: test_design_flaw, expr: {test_highly_coupled_to_implementation_details_not_contract: true}}, det: [{tool: aih, rule: "test_code_accessing_internal_state_or_mocking_private_methods"}, {tool: man, confidence: 0.6}], act: RCM, rat: "测试与实现过度耦合 -> 重构时测试大量失败 测试脆弱 关注点错误 ; #黑盒测试优先 #测试契约而非实现"}
  - {id: TST_008, lvl: M, sev: M, cat: TST, lang: "*", state: P, met: {type: test_quality, expr: {incomplete_test_setup_or_teardown_leading_to_state_leakage: true}}, det: [{tool: aih, rule: "analysis_of_test_lifecycle_methods_for_resource_allocation_deallocation"}], act: RCM, rat: "测试Setup/Teardown不完整 -> 测试间状态泄露 资源未释放 导致测试不可靠 ; #测试环境管理 #测试生命周期"}

  ## --- PRF: 性能与效率 ---
  - {id: PRF_001, lvl: S, sev: M, cat: PRF, lang: "*", state: P, met: {type: performance_hotspot, expr: {inefficient_collection_usage_in_hotspot: true}}, det: [{tool: aih, rule: "collection_api_usage_pattern_analysis_in_loops_or_high_traffic_code"}, {tool: prf, rule: "profiler_collection_allocation_analysis"}], act: RCM, rat: "集合类低效使用 -> 性能瓶颈 内存占用高 GC压力大 ; #数据结构 #性能优化"}
  - {id: PRF_006, lvl: S, sev: M, cat: PRF, lang: "*", state: P, met: {type: performance_hotspot, expr: {string_concatenation_in_loop_using_plus_operator: true}}, det: [{tool: spb, rule: "SSC_STRING_CONCATENATION_IN_LOOP"}, {tool: pmd, rule: "AvoidStringBufferField"}], act: RCM, rat: "循环中字符串拼接性能低 -> 创建大量临时字符串对象 GC压力大 ; #字符串性能 #StringBuilder优化"}
  - {id: PRF_007, lvl: S, sev: L, cat: PRF, lang: "java", state: P, met: {type: performance_detail, expr: {excessive_autoboxing_unboxing_in_hotspot: true}}, det: [{tool: spb, rule: "BX_BOXING_IMMEDIATELY_UNBOXED_TO_PERFORM_COERCION"}, {tool: aih, rule: "primitive_vs_wrapper_type_usage_in_hotspots_analysis"}], act: EDU, rat: "自动装箱/拆箱开销 -> 在性能热点区域可能导致不必要的对象创建和GC ; #Java性能细节 #基本类型与包装类"}

  ## --- MNT: 可维护性_演进与可操作性 ---
  - {id: MNT_001, lvl: S, sev: L, cat: MNT, lang: "*", state: P, met: {type: code_config_separation, expr: {configuration_values_hardcoded_in_code: true}}, det: [{tool: aih, rule: "hardcoded_config_value_pattern_detection"}, {tool: sg, rule: "hardcoded_ip_port_or_url_patterns"}], act: RCM, rat: "配置硬编码 -> 修改配置需重新编译部署 灵活性差 ; #配置管理 #可维护性"}
  - {id: MNT_008, lvl: S, sev: L, cat: MNT, lang: "*", state: T, met: {type: documentation_standard, expr: {module_or_component_lacks_readme_md: true}}, det: [{tool: aih, rule: "project_structure_scan_for_readme_files_and_quality_assessment"}, {tool: man, confidence: 0.3}], act: RCM, rat: "模块级README缺失 -> 新人理解模块困难 组件复用和集成成本高 ; #项目文档 #知识共享"}
  - {id: MNT_009, lvl: S, sev: L, cat: MNT, lang: "*", state: T, met: {type: versioning_practice, expr: {changelog_or_release_notes_missing_or_outdated: true}}, det: [{tool: git, rule: "commit_history_vs_changelog_update_frequency_analysis"}, {tool: man, confidence: 0.4}], act: EDU, rat: "变更日志不规范或缺失 -> 用户和开发者难以追踪版本变化 ; #版本发布 #变更管理"}

  ## --- CSH: 常识性启发与实习生陷阱 ---
  - {id: CSH_001, lvl: A, sev: M, cat: CSH, lang: "*", state: P, met: {type: common_pitfall, expr: {comparing_floating_point_numbers_with_exact_equality: true}}, det: [{tool: sg, rule: "float_equality_check_pattern"}, {tool: aih, rule: "numeric_comparison_context_analysis"}], act: RCM, rat: "浮点数直接用==比较 -> 因精度问题可能导致预期外结果 ; #编程基础 #浮点数陷阱"}
  - {id: CSH_011, lvl: A, sev: M, cat: CSH, lang: "*", state: P, met: {type: tech_adoption_risk, expr: {blind_adoption_of_trendy_tech_without_justification_score: ">0.6"}}, det: [{tool: aih, rule: "analysis_of_dependency_choices_vs_project_needs"}, {tool: man, confidence: 0.7}], act: CNF, rat: "新技术/库盲目应用 -> 引入不必要复杂性 学习曲线陡峭 运维风险高 ; #技术选型 #成熟度考量"}
  - {id: CSH_012, lvl: A, sev: M, cat: CSH, lang: "*", state: P, met: {type: library_understanding_gap, expr: {superficial_use_or_misunderstanding_of_core_library_features_score: ">0.5"}}, det: [{tool: aih, rule: "analysis_of_library_api_usage_patterns_for_common_misconceptions"}, {tool: man, confidence: 0.6}], act: EDU, rat: "对库或框架理解肤浅 -> 代码效率低下 实现方式笨拙 未充分利用其优势 ; #深度学习 #工具掌握"}

  ## --- L_*: 语言/框架特定规则 ---
  ### --- Java ---
  - {lang: java, id: L_JV_005, lvl: M, sev: M, cat: IMP, state: P, met: {type: best_practice_id, expr: {name: "java_string_equality_check_using_double_equals"}}, det: [{tool: spb, rule: "ES_COMPARING_STRINGS_WITH_EQ"}, {tool: pmd, rule: "UseEqualsToCompareStrings"}], act: FIX, autofix: {type: "regex_replace", find: '(\S+)\s*==\s*(\S+)', replace: "$1.equals($2)", condition: "is_string_comparison"}, rat: "Java字符串比较用==而非.equals() -> 可能因对象引用不同而判断错误 ; #Java基础 #字符串比较"}
  - {lang: java, id: L_JV_006, lvl: S, sev: L, cat: IMP, state: P, met: {type: best_practice_id, expr: {name: "java_prefer_interfaces_to_classes_for_type_declaration"}}, det: [{tool: aih, rule: "variable_declaration_and_method_parameter_type_analysis_for_interface_usage"}], act: RCM, rat: "倾向于使用接口声明类型 -> 代码更灵活 松耦合 易于替换实现 ; #EffectiveJava #面向接口编程"}
  - {lang: java, id: L_JV_007, lvl: M, sev: M, cat: RSRC, state: P, met: {type: pattern_id, expr: {name: "java_threadlocal_not_cleaned_up_potential_memory_leak"}}, det: [{tool: aih, rule: "threadlocal_variable_lifecycle_analysis_and_remove_method_usage_check"}, {tool: man, confidence: 0.7}], act: RCM, rat: "ThreadLocal未清理 -> 在长生命周期线程或线程池中可能导致内存泄露或数据串用 ; #Java并发 #ThreadLocal使用规范"}
  - {lang: java, id: L_JV_008, lvl: S, sev: M, cat: IMP, state: P, met: {type: best_practice_id, expr: {name: "java_avoid_finalizers_and_cleaners_unpredictable"}}, det: [{tool: spb, rule: "FI_FINALIZER_SHOULD_BE_AVOIDED"}, {tool: aih, rule: "presence_of_finalize_method_override_or_cleaner_usage_analysis"}], act: EDU, rat: "避免使用Finalizer和Cleaner -> 行为不可预测 执行缓慢 易出错 ; #EffectiveJava #资源回收"}
  - {lang: java, id: L_JV_009, lvl: M, sev: H, cat: SEC, state: P, met: {type: security_best_practice, expr: {name: "java_insecure_serialization_without_controls"}}, det: [{tool: sg, rule: "java_serialization_gadget_chain_potential_sink"}, {tool: aih, rule: "analysis_of_serializable_interface_usage_and_readobject_method"}], act: RQR, rat: "Java序列化安全控制不当 -> 易受反序列化攻击导致远程代码执行 ; #Java安全 #序列化漏洞"}
  - {lang: java, id: L_JV_010, lvl: S, sev: M, cat: PRF, state: P, met: {type: performance_pitfall, expr: {name: "java_stream_api_inefficient_use"}}, det: [{tool: aih, rule: "java_stream_usage_pattern_analysis_for_common_performance_anti_patterns"}, {tool: man, confidence: 0.6}], act: RCM, rat: "Java Stream API低效使用 -> 性能可能远不如传统循环 尤其在并行流中 ; #JavaStream #性能优化"}

  ### --- Python ---
  - {lang: py, id: L_PY_005, lvl: M, sev: M, cat: IMP, state: P, met: {type: best_practice_id, expr: {name: "python_misuse_of_new_vs_init"}}, det: [{tool: aih, rule: "analysis_of_class_constructor_patterns_and_usage_of_new"}], act: EDU, rat: "__new__与__init__职责混淆 -> 对象创建和初始化逻辑混乱 ; #Python对象模型 #魔术方法"}
  - {lang: py, id: L_PY_006, lvl: S, sev: M, cat: RSRC, state: P, met: {type: best_practice_id, expr: {name: "python_manual_resource_management_instead_of_with_statement"}}, det: [{tool: rfk, rule: "SIM115"}, {tool: pylint, rule: "W1514_try_finally_instead_of_with"}], act: FIX, autofix: {type: "ai_patch", prompt_template: "Refactor manual file/resource handling in {{code_snippet}} to use a 'with' statement."}, rat: "未使用with语句管理资源 -> 资源泄露风险高 代码冗余 ; #Python上下文管理器 #RAII"}
  - {lang: py, id: L_PY_007, lvl: M, sev: M, cat: IMP, state: P, met: {type: best_practice_id, expr: {name: "python_mutable_function_argument_modified_in_place_unexpectedly"}}, det: [{tool: aih, rule: "data_flow_analysis_for_in_place_modification_of_mutable_arguments"}], act: RCM, rat: "函数内修改可变参数未告知 -> 调用方预期之外的副作用 难以调试 ; #Python函数副作用 #防御性拷贝"}
  - {lang: py, id: L_PY_008, lvl: S, sev: L, cat: IMP, state: P, met: {type: naming_convention, expr: {name: "python_inconsistent_use_of_underscores_for_naming"}}, det: [{tool: aih, rule: "python_underscore_naming_convention_consistency_check"}], act: EDU, rat: "下划线命名约定误用 -> 混淆成员可见性或意图 ; #Python命名约定 #封装"}
  - {lang: py, id: L_PY_009, lvl: M, sev: H, cat: SEC, state: P, met: {type: security_vulnerability, expr: {name: "python_insecure_use_of_pickle_with_untrusted_data"}}, det: [{tool: sg, rule: "python.lang.security.pickle_usage.pickle-deserialization"}, {tool: rfk, rule: "S301"}], act: RQR, rat: "不安全使用pickle反序列化 -> 可导致任意代码执行 ; #Python安全 #反序列化漏洞"}
  - {lang: py, id: L_PY_010, lvl: S, sev: M, cat: CNC, state: P, met: {type: concurrency_pitfall, expr: {name: "python_misunderstanding_gil_limitations_or_async_misuse"}}, det: [{tool: aih, rule: "analysis_of_threading_vs_multiprocessing_vs_asyncio_choice"}], act: EDU, rat: "对GIL或async理解不足 -> 并发性能未达预期或引入不必要复杂性 ; #Python并发 #GIL #asyncio"}

  ### --- JS/TS ---
  - {lang: [js,ts], id: L_JS_003, lvl: M, sev: M, cat: IMP, state: P, met: {type: language_pitfall, expr: {name: "js_this_keyword_binding_issue"}}, det: [{tool: esl, rule: "no-invalid-this"}, {tool: aih, rule: "analysis_of_this_usage_in_different_function_scopes"}], act: RCM, rat: "'this'指向混淆 -> 运行时错误 行为不符合预期 ; #JavaScript核心 #this绑定"}
  - {lang: [js,ts], id: L_JS_004, lvl: S, sev: L, cat: IMP, state: P, met: {type: best_practice_id, expr: {name: "js_use_of_loose_equality_vs_strict_equality"}}, det: [{tool: esl, rule: "eqeqeq"}], act: FIX, autofix: {type: "regex_replace", find: "==", replace: "===", condition: "not_comparing_with_null_intentionally"}, rat: "使用非严格相等(==) -> 可能因类型转换导致意外的比较结果 ; #JavaScript基础 #类型安全比较"}
  - {lang: [js,ts], id: L_JS_005, lvl: M, sev: M, cat: IMP, state: P, met: {type: language_pitfall, expr: {name: "js_var_hoisting_or_scope_issue_use_let_const"}}, det: [{tool: esl, rule: "no-var"}, {tool: aih, rule: "analysis_of_variable_declarations_and_scoping_rules_usage"}], act: EDU, rat: "变量提升或作用域混淆 -> 难以追踪的Bug 变量值不符合预期 ; #JavaScript作用域 #let_const_vs_var"}
  - {lang: ts, id: L_TS_002, lvl: S, sev: M, cat: IMP, state: P, met: {type: best_practice_id, expr: {name: "ts_underutilization_of_utility_types"}}, det: [{tool: aih, rule: "analysis_of_type_definitions_for_utility_types_opportunities"}], act: EDU, rat: "TS Utility Types使用不足 -> 类型定义冗余或不精确 手动实现类型转换易错 ; #TypeScript高级类型 #代码简洁性"}
  - {lang: ts, id: L_TS_003, lvl: M, sev: M, cat: DSN, state: P, met: {type: best_practice_id, expr: {name: "ts_overuse_of_numeric_enums_vs_string_literals"}}, det: [{tool: aih, rule: "analysis_of_enum_definitions_vs_string_literal_union_alternatives"}], act: RCM, rat: "Enum使用场景不当 -> 数字Enum可读性差 序列化问题 Bundle体积增加 ; #TypeScript枚举 #类型设计"}

  ### --- Go ---
  - {lang: go, id: L_GO_001, lvl: M, sev: C, cat: IMP, state: P, met: {type: best_practice_id, expr: {name: "go_error_handling_not_checked_or_swallowed"}}, det: [{tool: sa, rule: "golangci_lint_errcheck"}, {tool: aih, rule: "go_error_return_value_usage_analysis"}], act: RQR, rat: "Go错误未检查或忽略 -> 关键问题被掩盖 程序行为异常 ; #EffectiveGo #错误处理"}
  - {lang: go, id: L_GO_003, lvl: S, sev: M, cat: DSN, state: P, met: {type: best_practice_id, expr: {name: "go_interface_large_or_defined_by_provider"}}, det: [{tool: aih, rule: "go_interface_size_and_definition_location_analysis"}], act: EDU, rat: "Go接口设计不当 -> 耦合性增加 接口应小且由消费方定义 ; #EffectiveGo #接口设计"}
  - {lang: go, id: L_GO_004, lvl: M, sev: M, cat: MNT, state: P, met: {type: best_practice_id, expr: {name: "go_package_naming_or_organization_unidiomatic_or_cyclic"}}, det: [{tool: sa, rule: "golangci_lint_gocyclo_or_import_cycles_check"}, {tool: aih, rule: "go_package_naming_conventions_and_module_structure_analysis"}], act: RCM, rat: "Go包命名或组织混乱 -> 导入路径不清晰 易产生循环依赖 结构难理解 ; #Go项目结构 #包设计"}
  - {lang: go, id: L_GO_005, lvl: S, sev: L, cat: RSRC, state: P, met: {type: best_practice_id, expr: {name: "go_defer_misuse_in_loop_or_late_defer"}}, det: [{tool: aih, rule: "go_defer_usage_pattern_analysis_for_performance_and_correctness"}], act: EDU, rat: "Go defer使用不当 -> 可能导致性能问题或资源未及时释放 ; #Go defer语句 #资源管理"}

  ### --- C++ ---
  - {lang: cpp, id: L_CPP_001, lvl: M, sev: C, cat: RSRC, state: P, met: {type: best_practice_id, expr: {name: "cpp_rule_of_three_five_zero_violation"}}, det: [{tool: cppcheck, rule: "ruleOfThree"}, {tool: aih, rule: "class_member_resource_analysis_vs_special_member_functions"}], act: RQR, rat: "C++三/五/零法则违背 -> 内存泄露 悬垂指针 双重释放 ; #CppCoreGuidelines #RAII"}
  - {lang: cpp, id: L_CPP_002, lvl: S, sev: M, cat: IMP, state: P, met: {type: best_practice_id, expr: {name: "cpp_prefer_const_constexpr_underused"}}, det: [{tool: clang-tidy, rule: "modernize-use-trailing-return-type"}, {tool: aih, rule: "variable_and_function_analysis_for_const_constexpr_opportunities"}], act: RCM, rat: "const/constexpr使用不足 -> 可变性过高 错过编译期优化和安全增强 ; #CppCoreGuidelines #常量正确性"}
  - {lang: cpp, id: L_CPP_003, lvl: M, sev: C, cat: RSRC, state: P, met: {type: best_practice_id, expr: {name: "cpp_use_of_raw_pointers_for_ownership"}}, det: [{tool: aih, rule: "raw_pointer_usage_analysis_vs_smart_pointers"}, {tool: clang-tidy, rule: "modernize-use-smart-pointers"}], act: RCM, rat: "使用裸指针管理资源 -> 易导致资源泄露和所有权混淆 ; #CppCoreGuidelines #智能指针"}

  ### --- C# ---
  - {lang: csharp, id: L_CS_001, lvl: M, sev: C, cat: RSRC, state: P, met: {type: best_practice_id, expr: {name: "csharp_idisposable_misuse_or_using_missing"}}, det: [{tool: roslyn, rule: "CA2000_CA2213"}, {tool: aih, rule: "unmanaged_resource_holder_analysis_vs_idisposable_using_patterns"}], act: RQR, rat: "C# IDisposable实现或使用不当 -> 资源泄露 ; #CSharp #IDisposable #using语句"}
  - {lang: csharp, id: L_CS_002, lvl: S, sev: M, cat: CNC, state: P, met: {type: best_practice_id, expr: {name: "csharp_async_await_misuse_blocking_or_async_void"}}, det: [{tool: roslyn, rule: "VSTHRD002_VSTHRD100"}, {tool: aih, rule: "async_method_signature_and_await_usage_analysis"}], act: RCM, rat: "C# async/await误用 -> 死锁 UI卡顿 未处理异常 ; #CSharpAsync #TAP"}
  - {lang: csharp, id: L_CS_003, lvl: S, sev: L, cat: IMP, state: P, met: {type: best_practice_id, expr: {name: "csharp_linq_inefficient_use_multiple_enumeration"}}, det: [{tool: aih, rule: "linq_query_analysis_for_multiple_enumerations_or_deferred_execution_issues"}], act: RCM, rat: "LINQ低效使用 -> 多次枚举导致性能下降 ; #CSharpLINQ #性能"}

  ### --- Ruby ---
  - {lang: ruby, id: L_RB_001, lvl: M, sev: M, cat: IMP, state: P, met: {type: style_guide_adherence, expr: {name: "ruby_style_guide_violations_rubocop_offenses"}}, det: [{tool: rubocop, rule: "major_offense_count_and_severity_analysis"}], act: FIX, autofix: {type: "tool_command", command: "rubocop -a"}, rat: "Ruby风格指南违背 -> 代码可读性和一致性差 ; #RubyStyleGuide #Rubocop"}
  - {lang: ruby, id: L_RB_002, lvl: S, sev: M, cat: PRF, state: P, met: {type: performance_pitfall, expr: {name: "ruby_inefficient_block_or_iterator_usage"}}, det: [{tool: aih, rule: "ruby_block_iterator_pattern_analysis_for_performance_hotspots"}, {tool: prf, rule: "ruby_profiler_memory_allocation_analysis"}], act: RCM, rat: "Ruby块或迭代器低效使用 -> 性能问题 内存消耗大 ; #RubyPerformance #Enumerable"}
  - {lang: ruby, id: L_RB_003, lvl: A, sev: M, cat: IMP, state: P, met: {type: best_practice_id, expr: {name: "ruby_excessive_monkey_patching"}}, det: [{tool: aih, rule: "analysis_of_core_class_reopening_and_method_redefinition"}, {tool: man, confidence: 0.8}], act: RCM, rat: "过度猴子补丁 -> 代码行为不可预测 调试困难 库升级风险高 ; #RubyPitfalls #MonkeyPatching"}

  ### --- Rust ---
  - {lang: rust, id: L_RS_001, lvl: M, sev: C, cat: RSRC, state: P, met: {type: ownership_borrowing_error, expr: {name: "rust_borrow_checker_errors_or_lifetime_issues"}}, det: [{tool: rustc, rule: "borrow_checker_error_analysis_clippy_lints"}], act: RQR, rat: "Rust所有权/借用/生命周期错误 -> 内存安全问题 编译失败 ; #RustOwnership #BorrowChecker"}
  - {lang: rust, id: L_RS_002, lvl: S, sev: M, cat: IMP, state: P, met: {type: idiomatic_code, expr: {name: "rust_unidiomatic_code_excessive_mut_clone_ignore_result_option"}}, det: [{tool: rustc, rule: "clippy_pedantic_or_style_lints"}, {tool: aih, rule: "rust_idiomatic_pattern_analysis_result_option_handling"}], act: EDU, rat: "非惯用Rust代码 -> 未充分利用语言特性 安全性或性能可能受损 ; #IdiomaticRust #ErrorHandlingRust"}
  - {lang: rust, id: L_RS_003, lvl: M, sev: H, cat: IMP, state: P, met: {type: safety_issue, expr: {name: "rust_unsafe_code_misuse_without_strong_justification"}}, det: [{tool: aih, rule: "unsafe_block_usage_analysis_and_justification_check"}, {tool: sg, rule: "rust_unsafe_patterns"}], act: RQR, rat: "不安全(unsafe)代码误用 -> 可能破坏Rust的内存安全保证 ; #RustSafety #UnsafeCode"}
