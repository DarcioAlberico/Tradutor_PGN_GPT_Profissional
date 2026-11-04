package org.languagetool.server;

import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.languagetool.*;
import org.languagetool.rules.RuleMatch;

/** Test only: inspect synthetic markers in pool and Language static state.
 * No heap dump, request, response or marker is written to an artifact.
 */
public class PoolPrivacyProbe {
  static IdentityHashMap<Object, Boolean> seen;
  static Set<Class<?>> scannedClasses;
  static List<String> hits;
  static Set<String> inaccessible;
  static String needle;

  static void walk(Object object, String path) throws Exception {
    if (object == null || seen.put(object, Boolean.TRUE) != null) return;
    if (seen.size() > 5000000) throw new IllegalStateException("graph_budget_exceeded");
    Class<?> type = object.getClass();
    if (object instanceof String) {
      if (((String)object).contains(needle)) hits.add(path);
      return;
    }
    // JVM execution infrastructure is outside this pipeline-state assertion.
    if (object instanceof Class || object instanceof ClassLoader || object instanceof Thread || object instanceof Module
      || type.getName().startsWith("java.lang.invoke.") || type.getName().startsWith("sun.invoke.")) return;
    if (type.isArray()) {
      if (object instanceof char[]) {
        if (new String((char[])object).contains(needle)) hits.add(path + "[chars]");
      } else if (object instanceof byte[]) {
        if (new String((byte[])object, StandardCharsets.UTF_8).contains(needle)) hits.add(path + "[bytes]");
      } else if (!type.getComponentType().isPrimitive()) {
        for (int i = 0; i < Array.getLength(object); i++) walk(Array.get(object, i), path + "[]");
      }
      return;
    }
    for (Class<?> cls = type; cls != null; cls = cls.getSuperclass()) {
      boolean includeStatic = !cls.getName().startsWith("java.") && scannedClasses.add(cls);
      for (Field field : cls.getDeclaredFields()) {
        if (field.getType().isPrimitive()) continue;
        boolean isStatic = Modifier.isStatic(field.getModifiers());
        if (isStatic && !includeStatic) continue;
        if (!field.trySetAccessible()) {
          inaccessible.add(cls.getName() + "." + field.getName());
          continue;
        }
        walk(field.get(isStatic ? null : object), path + "." + cls.getSimpleName() + "." + field.getName());
      }
    }
  }

  static void snapshot(Object root, String label) throws Exception {
    seen = new IdentityHashMap<>();
    scannedClasses = new HashSet<>();
    hits = new ArrayList<>();
    inaccessible = new TreeSet<>();
    walk(root, "pool");
    int poolMatches = hits.size();
    // A disabled pool no longer reaches its former pipelines. Grammar filters
    // can still use this independent static speller, so scan it explicitly.
    Field spellingRules = Language.class.getDeclaredField("spellingRules");
    spellingRules.setAccessible(true);
    walk(spellingRules.get(null), "Language.spellingRules");
    System.out.println(label + " visited=" + seen.size() + " matches=" + hits.size() + " inaccessible=" + inaccessible.size()
      + " pool_matches=" + poolMatches);
    for (String hit : hits) System.out.println("retained_path=" + hit);
    for (String field : inaccessible) System.out.println("inaccessible=" + field);
  }

  static PipelineSettings settings(HTTPServerConfig config, List<String> disabled) {
    TextChecker.QueryParams query = new TextChecker.QueryParams(Collections.emptyList(), Collections.emptyList(), disabled,
      Collections.emptyList(), Collections.emptyList(), false, true, false, false, false, false,
      JLanguageTool.Mode.ALL, JLanguageTool.Level.DEFAULT, null, false);
    return new PipelineSettings(Languages.getLanguageForShortCode("pt-BR"), null, query, config.globalConfig, new UserConfig());
  }

  static List<String> check(PipelinePool pool, PipelineSettings settings, String text) throws Exception {
    Pipeline pipeline = pool.getPipeline(settings);
    try {
      List<String> signature = new ArrayList<>();
      for (RuleMatch match : pipeline.check(text)) {
        signature.add(match.getRule().getId() + ":" + match.getFromPos() + ":" + match.getToPos()
          + ":" + match.getSuggestedReplacements());
      }
      return signature;
    } finally {
      pool.returnPipeline(settings, pipeline);
    }
  }

  public static void main(String[] args) throws Exception {
    needle = new Scanner(System.in).nextLine();
    if (!"6.6".equals(JLanguageTool.VERSION)) throw new IllegalStateException("requires_languagetool_6_6");
    HTTPServerConfig config = new HTTPServerConfig(new String[]{"--config", args[0]});
    if (config.getCacheSize() != 0) throw new IllegalStateException("result_cache_must_be_disabled");
    PipelinePool pool = new PipelinePool(config, null, false);
    PipelineSettings normal = settings(config, Collections.emptyList());
    PipelineSettings disabled = settings(config, Collections.singletonList("LIGACAO_ECG_V3"));
    // Synthetic positive example from the bundled pt grammar.xml. Preserve
    // grammar with spelling disabled and verify configuration A/B/A isolation.
    List<String> grammar = check(pool, normal, "A palavra está correto.");
    if (grammar.stream().noneMatch(result -> result.startsWith("LIGACAO_ECG_V3:"))) {
      throw new IllegalStateException("grammar_positive_control_missing");
    }
    List<String> withoutRule = check(pool, disabled, "A palavra está correto.");
    if (withoutRule.stream().anyMatch(result -> result.startsWith("LIGACAO_ECG_V3:"))) {
      throw new IllegalStateException("disabled_rule_still_active");
    }
    if (!check(pool, normal, "A palavra está correto.").equals(grammar)) {
      throw new IllegalStateException("grammar_control_not_restored");
    }
    check(pool, normal, "");
    snapshot(pool, "before");
    if (args.length > 1 && args[1].equals("initial-only")) return;
    String normalText = "As peça branca estão ativos. " + needle + ".";
    List<String> original = check(pool, normal, normalText);
    snapshot(pool, "after_check");
    check(pool, normal, "");
    snapshot(pool, "after_empty_check");
    check(pool, disabled, "🙂 As peça branca estão ativos. " + needle + " posição\u0301.");
    snapshot(pool, "after_disabled_rules");
    List<String> restored = check(pool, normal, normalText);
    if (!restored.equals(original)) throw new IllegalStateException("grammar_changed_after_rule_restore");
    snapshot(pool, "after_restored_rules");
  }
}
