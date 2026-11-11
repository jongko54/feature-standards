package dev.featurestandards.generated.core;

import java.util.List;
import java.util.Map;

/** Server-owned product data; provider replacement is application construction only. */
@FunctionalInterface
public interface DocumentProvider {
    List<Map<String, Object>> load() throws Exception;
}
