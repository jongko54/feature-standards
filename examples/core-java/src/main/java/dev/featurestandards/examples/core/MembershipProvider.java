package dev.featurestandards.examples.core;

import dev.featurestandards.auth.AuthService;
import dev.featurestandards.core.authorization.Principal;

/** Resolve current membership from a server-owned service, never request headers. */
@FunctionalInterface
public interface MembershipProvider {
    Principal resolve(AuthService.User user) throws Exception;
}
