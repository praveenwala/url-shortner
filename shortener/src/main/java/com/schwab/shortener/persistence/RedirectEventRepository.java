package com.schwab.shortener.persistence;

import com.schwab.shortener.domain.RedirectEvent;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface RedirectEventRepository extends JpaRepository<RedirectEvent, Long> {

    @Query("select count(e) from RedirectEvent e where e.code = :code")
    long countByCode(@Param("code") String code);
}
