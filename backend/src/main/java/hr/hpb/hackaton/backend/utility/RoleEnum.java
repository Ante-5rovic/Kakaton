package hr.hpb.hackaton.backend.utility;

public enum RoleEnum {

    ADMIN(1L, "ADMIN"),
    USER(2L, "USER");

    private Long id;

    private String roleName;

    RoleEnum(Long id, String roleName) {
        this.id = id;
        this.roleName = roleName;
    }

    public Long getId() {
        return id;
    }

    public String getRoleName() {
        return roleName;
    }


}
