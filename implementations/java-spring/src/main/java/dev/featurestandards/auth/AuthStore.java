package dev.featurestandards.auth;

/** Storage boundary shared by HTTP and non-HTTP consumers. Mutations return only after commit. */
public interface AuthStore {
    AuthService.Login login(String peer, String previous, String email, String password);
    AuthService.Session session(String token);
    boolean logout(String token, String csrf);
    default int account(String action, String peer, String email, String token, String password) {
        throw new StorageUnavailableException();
    }
    default void checkReady() { }
}
