# Trazelio Sport — esqueleto de la plataforma

## Capas
Plataforma (tú) → Club (director) → Categoría (entrenadores) → Jugador ↔ Acudiente

| Rol | Ve y hace |
|---|---|
| Plataforma | `/plataforma`: clubes, planes, suspender, sumar días |
| admin (director) | Todo su club: usuarios, categorías, configuración, tarifas, avisos, reportes de dinero |
| entrenador | Solo sus categorías: deportistas, fichas, rostros, asistencia, partidos/entrenos, estadísticas, cobros y caja |
| kiosco | Solo la cámara de asistencia |
| acudiente | Enlace privado: carta, números, asistencia y pagos |
| jugador | Enlace privado: carta, números, logros; edita apodo, lema, foto (aprobada por entrenador) |

## Módulos
Landing · Registro · Suscripción (mensual/anual, webhook) · Resumen · Asistencia (nombre / documento / facial / sin conexión) · Deportistas y fichas · Rostros · Partidos y entrenos · Estadísticas y carta del jugador · Cobros y tienda · Inventario · Caja ciega · Avisos WhatsApp · Reportes (Excel/impresión) · Usuarios y perfiles con foto · Estructura · App instalable

## Datos
Plataforma: clubes (slug, plan, estado, vence).  Por club (SQLite propio): club, usuarios, usuario_categorias, deportistas, rostros, asistencias, eventos, estadisticas, mensualidades, tarifas, productos, ventas, venta_items, cajas, egresos, avisos, ajustes.

## Pendiente para escalar
PostgreSQL si pasas de cientos de clubes · pasarela de pago real (webhook) · cobros sin conexión · notificaciones push · ranking opcional por club · app nativa si la PWA se queda corta.
