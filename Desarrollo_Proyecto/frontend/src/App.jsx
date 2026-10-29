import { useState, useEffect, useRef } from "react";

const API = "http://localhost:8000";

// Los precios en Chile no llevan decimales
const pesos = (n) =>
  n == null ? "—" : "$" + Math.round(n).toLocaleString("es-CL");

// La clave lleva barras verticales, que hay que codificar en la URL
const ruta = (base, clave) => `${API}/${base}/${encodeURIComponent(clave)}`;

const capitalizar = (t) =>
  t ? t.charAt(0).toUpperCase() + t.slice(1) : "";

// "500.0mg" se lee mejor como "500 mg"
function legibleConcentracion(c) {
  if (!c) return "";
  return c
    .replace(/(\d+)\.0(?=[a-z])/gi, "$1")
    .replace(/(\d)([a-z])/i, "$1 $2");
}

const NOMBRE_FAMILIA = {
  solido_oral: "comprimidos o cápsulas",
  liberacion_modificada: "liberación prolongada",
  liquido_oral: "jarabe, gotas o solución",
  inyectable: "inyectable",
  topico: "uso tópico",
  oftalmico: "gotas oftálmicas",
  otico: "gotas óticas",
  nasal: "uso nasal",
  rectal: "supositorios",
  vaginal: "óvulos",
  sublingual: "sublingual",
  inhalatorio: "inhalación",
  transdermico: "parches",
};

/* ---------------------------------------------------------
   El sello amarillo distingue lo certificado por el ISP de
   lo que solo declara la farmacia. No es lo mismo y el
   usuario debe poder notarlo.
   --------------------------------------------------------- */
function SelloBio({ valor, fuente }) {
  if (!valor) return null;

  const certificado = fuente === "isp";

  return (
    <span
      className={`sello-bio ${certificado ? "certificado" : "declarado"}`}
      title={
        certificado
          ? "Bioequivalencia certificada por el Instituto de Salud Pública"
          : "Bioequivalencia declarada por la farmacia, sin verificar contra el registro del ISP"
      }
    >
      <span className="punto" />
      {certificado ? "Bioequivalente ISP" : "Bioequivalente según farmacia"}
    </span>
  );
}

/* --------------------- Gráfico de precio histórico --------------------- */

// "2026-09-07" -> "7 sept". Se arma la fecha a mano para que la zona
// horaria no la corra un dia
const fechaCorta = (iso) => {
  const [a, m, d] = iso.split("-").map(Number);
  return new Date(a, m - 1, d).toLocaleDateString("es-CL", {
    day: "numeric",
    month: "short",
  });
};

const fechaLarga = (iso) => {
  const [a, m, d] = iso.split("-").map(Number);
  return new Date(a, m - 1, d).toLocaleDateString("es-CL", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
};

// Escala "redonda" para el eje: 0, 1.000, 2.000... en vez de 0, 873, 1.746
function marcasEje(maximo, cantidad = 4) {
  if (!maximo) return [0];
  const bruto = maximo / cantidad;
  const potencia = 10 ** Math.floor(Math.log10(bruto));
  const paso = [1, 2, 2.5, 5, 10].map((x) => x * potencia).find((x) => x >= bruto);
  const marcas = [];
  for (let v = 0; v <= maximo + paso * 0.001; v += paso) marcas.push(v);
  if (marcas[marcas.length - 1] < maximo) marcas.push(marcas[marcas.length - 1] + paso);
  return marcas;
}

const ALTO = 260;
const MARGEN = { arriba: 16, derecha: 16, abajo: 32, izquierda: 64 };

function GraficoHistorial({ serie }) {
  const contenedor = useRef(null);
  const [ancho, setAncho] = useState(640);
  const [foco, setFoco] = useState(null);

  // El SVG se dibuja al ancho real para que el texto no se deforme
  useEffect(() => {
    const nodo = contenedor.current;
    if (!nodo) return;
    const observador = new ResizeObserver(([e]) => setAncho(e.contentRect.width));
    observador.observe(nodo);
    return () => observador.disconnect();
  }, []);

  const tiempos = serie.map((p) => {
    const [a, m, d] = p.fecha_muestreo.split("-").map(Number);
    return Date.UTC(a, m - 1, d);
  });
  const marcas = marcasEje(Math.max(...serie.map((p) => p.precio_min)));
  const tope = marcas[marcas.length - 1];

  const interior = ancho - MARGEN.izquierda - MARGEN.derecha;
  const t0 = tiempos[0];
  const rango = tiempos[tiempos.length - 1] - t0 || 1;
  const x = (i) => MARGEN.izquierda + ((tiempos[i] - t0) / rango) * interior;
  const y = (v) => MARGEN.arriba + (1 - v / tope) * (ALTO - MARGEN.arriba - MARGEN.abajo);

  const trazo = serie.map((p, i) => `${i ? "L" : "M"}${x(i)},${y(p.precio_min)}`).join(" ");

  // Etiquetas del eje x: primera, ultima y las intermedias que no se
  // encimen. Se mide en pixeles porque las fechas no son equidistantes
  const SEPARACION = 70;
  const ultima = serie.length - 1;
  const etiquetasX = [0];
  for (let i = 1; i < ultima; i++) {
    const libre =
      x(i) - x(etiquetasX[etiquetasX.length - 1]) >= SEPARACION &&
      x(ultima) - x(i) >= SEPARACION;
    if (libre) etiquetasX.push(i);
  }
  if (ultima > 0 && x(ultima) - x(0) >= SEPARACION) etiquetasX.push(ultima);

  function alMover(e) {
    const caja = e.currentTarget.getBoundingClientRect();
    const px = e.clientX - caja.left;
    let cercano = 0;
    serie.forEach((_, i) => {
      if (Math.abs(x(i) - px) < Math.abs(x(cercano) - px)) cercano = i;
    });
    setFoco(cercano);
  }

  const punto = foco != null ? serie[foco] : null;

  return (
    <div className="grafico" ref={contenedor}>
      <svg
        width={ancho}
        height={ALTO}
        role="img"
        aria-label={`Mejor precio entre ${fechaLarga(serie[0].fecha_muestreo)} y ${fechaLarga(serie[serie.length - 1].fecha_muestreo)}`}
        onPointerMove={alMover}
        onPointerLeave={() => setFoco(null)}
      >
        {marcas.map((v) => (
          <g key={v}>
            <line
              className="grafico-reja"
              x1={MARGEN.izquierda}
              x2={ancho - MARGEN.derecha}
              y1={y(v)}
              y2={y(v)}
            />
            <text className="grafico-eje" x={MARGEN.izquierda - 10} y={y(v)} dy="0.32em" textAnchor="end">
              {pesos(v)}
            </text>
          </g>
        ))}

        {etiquetasX.map((i) => (
          <text
            key={i}
            className="grafico-eje"
            x={x(i)}
            y={ALTO - 8}
            textAnchor={i === 0 ? "start" : i === serie.length - 1 ? "end" : "middle"}
          >
            {fechaCorta(serie[i].fecha_muestreo)}
          </text>
        ))}

        <path className="grafico-linea" d={trazo} />

        {punto && (
          <g>
            <line
              className="grafico-guia"
              x1={x(foco)}
              x2={x(foco)}
              y1={MARGEN.arriba}
              y2={ALTO - MARGEN.abajo}
            />
            <circle className="grafico-punto" cx={x(foco)} cy={y(punto.precio_min)} r={5} />
          </g>
        )}
      </svg>

      {punto && (
        <div
          className="grafico-tooltip"
          style={{
            left: Math.min(Math.max(x(foco), 90), ancho - 90),
            top: y(punto.precio_min),
          }}
        >
          <strong>{pesos(punto.precio_min)}</strong>
          <span>{fechaLarga(punto.fecha_muestreo)}</span>
          <span>
            {punto.farmacias} {punto.farmacias === 1 ? "farmacia" : "farmacias"} con precio
          </span>
        </div>
      )}
    </div>
  );
}

function Historial({ clave }) {
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setDatos(null);
    setError(null);

    fetch(ruta("historial", clave))
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(setDatos)
      .catch(() => setError("No se pudo cargar el historial de precios."));
  }, [clave]);

  if (error) return <p className="aviso">{error}</p>;
  if (!datos) return <p className="aviso">Cargando historial…</p>;

  const serie = datos.serie;
  if (serie.length < 2) {
    return (
      <p className="aviso">
        Todavía hay una sola medición de precio para este envase. El gráfico
        aparecerá cuando se acumulen más fechas.
      </p>
    );
  }

  const primero = serie[0].precio_min;
  const ultimo = serie[serie.length - 1].precio_min;
  const cambio = primero ? Math.round((100 * (ultimo - primero)) / primero) : 0;

  return (
    <div className="historial">
      <div className="historial-cifras">
        <div>
          <span>Hoy</span>
          <strong>{pesos(ultimo)}</strong>
        </div>
        <div>
          <span>Mínimo</span>
          <strong>{pesos(datos.resumen.precio_min)}</strong>
        </div>
        <div>
          <span>Máximo</span>
          <strong>{pesos(datos.resumen.precio_max)}</strong>
        </div>
        <div>
          <span>Desde el {fechaCorta(serie[0].fecha_muestreo)}</span>
          <strong className={cambio > 0 ? "sube" : cambio < 0 ? "baja" : ""}>
            {cambio > 0 ? "▲" : cambio < 0 ? "▼" : "="} {Math.abs(cambio)}%
          </strong>
        </div>
      </div>

      <GraficoHistorial serie={serie} />

      <details className="historial-tabla">
        <summary>Ver los datos en una tabla</summary>
        <table>
          <thead>
            <tr>
              <th>Fecha</th>
              <th>Mejor precio</th>
              <th>Farmacias con precio</th>
            </tr>
          </thead>
          <tbody>
            {serie.map((p) => (
              <tr key={p.fecha_muestreo}>
                <td>{fechaLarga(p.fecha_muestreo)}</td>
                <td>{pesos(p.precio_min)}</td>
                <td>{p.farmacias}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}

/* --------------------- Tarjeta de presentación --------------------- */

function Tarjeta({ datos, href }) {
  const envases = datos.envases || [];

  return (
    <a className="tarjeta" href={href}>
      <figure>
        {datos.url_imagen ? (
          <img src={datos.url_imagen} alt="" loading="lazy" />
        ) : (
          <span className="sin-foto">Sin fotografía</span>
        )}
      </figure>

      <div className="tarjeta-cuerpo">
        <div className="principio">{capitalizar(datos.principio_activo)}</div>
        <div className="dosis">
          {legibleConcentracion(datos.concentracion)}
          {datos.familia && ` · ${NOMBRE_FAMILIA[datos.familia] || datos.familia}`}
        </div>

        {datos.hay_bioequivalente && (
          <div className="tarjeta-sello">
            <span className="sello-bio declarado">
              <span className="punto" />
              Hay bioequivalentes
            </span>
          </div>
        )}

        <div className="tarjeta-pie">
          <div>
            <div className="desde">Desde</div>
            <div className="precio-principal">{pesos(datos.precio_desde)}</div>
          </div>
          <div className="donde">
            {envases.length === 1
              ? `${envases[0]} unidades`
              : `${envases.length} presentaciones`}
            <br />
            {datos.farmacias.length === 1 ? "1 farmacia" : `${datos.farmacias.length} farmacias`}
          </div>
        </div>

        <span className="tarjeta-accion">Ver precios e historial →</span>
      </div>
    </a>
  );
}

/* --------------------- Comparación entre farmacias --------------------- */

function Comparacion({ clave }) {
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setDatos(null);
    setError(null);

    fetch(ruta("comparar", clave))
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(setDatos)
      .catch(() => setError("No se pudieron cargar las opciones."));
  }, [clave]);

  if (error) return <p className="aviso">{error}</p>;
  if (!datos) return <p className="aviso">Cargando opciones…</p>;

  return (
    <>
      {datos.ahorro && datos.ahorro.monto > 0 && (
        <div className="resumen-ahorro">
          Entre la opción más económica y la más cara hay{" "}
          <strong>{pesos(datos.ahorro.monto)} de diferencia</strong>, un{" "}
          {datos.ahorro.porcentaje}% sobre el mismo medicamento y la misma
          cantidad.
        </div>
      )}

      <div className="opciones">
        {datos.productos.map((p, i) => (
          <article key={p.id} className={`opcion ${i === 0 ? "mejor" : ""}`}>
            <div>
              {i === 0 && <span className="etiqueta-mejor">Mejor precio</span>}
              <div className="opcion-nombre">{p.nombre_publicado}</div>

              <div className="opcion-meta">
                <span className="farmacia">{p.farmacia}</span>
                {p.condicion_venta && <span>{capitalizar(p.condicion_venta.toLowerCase())}</span>}
                {p.fecha_muestreo && <span>Precio al {p.fecha_muestreo}</span>}
                <SelloBio valor={p.bioequivalente} fuente={p.bioequivalente_fuente} />
              </div>

              {p.url_producto && (
                <a
                  className="ir"
                  href={p.url_producto}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Ver en {p.farmacia}
                </a>
              )}

              {p.nombre_oficial && (
                <div className="oficial">
                  Registro sanitario: {p.nombre_oficial}
                  {p.laboratorio_oficial && ` · ${p.laboratorio_oficial}`}
                </div>
              )}
            </div>

            <div className="opcion-precio">
              <div className="precio">{pesos(p.precio_oferta)}</div>
              {p.en_oferta && (
                <div className="precio-antes">{pesos(p.precio_normal)}</div>
              )}
              {p.precio_unitario && (
                <div className="unitario">{pesos(p.precio_unitario)} por unidad</div>
              )}
            </div>
          </article>
        ))}
      </div>
    </>
  );
}

/* --------------------- Navegación --------------------- */

// Rutas en el hash (#/medicamento/<clave>): no requieren configurar el
// servidor, el boton Atras del navegador funciona y el enlace se puede
// compartir.
const PREFIJO_MEDICAMENTO = "#/medicamento/";

const enlaceMedicamento = (clave) =>
  PREFIJO_MEDICAMENTO + encodeURIComponent(clave);

function leerRuta() {
  const hash = window.location.hash;
  if (hash.startsWith(PREFIJO_MEDICAMENTO)) {
    return { pagina: "medicamento", clave: decodeURIComponent(hash.slice(PREFIJO_MEDICAMENTO.length)) };
  }
  return { pagina: "inicio" };
}

function useRuta() {
  const [ruta, setRuta] = useState(leerRuta);

  useEffect(() => {
    const alCambiar = () => {
      setRuta(leerRuta());
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", alCambiar);
    return () => window.removeEventListener("hashchange", alCambiar);
  }, []);

  return ruta;
}

/* --------------------- Página de un medicamento --------------------- */

function PaginaMedicamento({ clave, hayBusqueda }) {
  const [datos, setDatos] = useState(null);
  const [elegido, setElegido] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setDatos(null);
    setElegido(null);
    setError(null);

    fetch(ruta("presentacion", clave))
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d) => {
        setDatos(d);
        // Se abre en el tamanio con mas opciones: es donde la
        // comparacion aporta mas
        const conMasOpciones = [...d.tamanios].sort(
          (a, b) => b.farmacias - a.farmacias
        )[0];
        if (conMasOpciones) setElegido(conMasOpciones.clave_equivalencia);
      })
      .catch((estado) =>
        setError(
          estado === 404
            ? "Este medicamento ya no tiene precios disponibles."
            : "No se pudo cargar este medicamento. Revisa que la API esté corriendo."
        )
      );
  }, [clave]);

  // Si se llego desde una busqueda, volver la deja tal como estaba
  function volver(e) {
    if (hayBusqueda) {
      e.preventDefault();
      window.history.back();
    }
  }

  const tamanio = datos?.tamanios.find((t) => t.clave_equivalencia === elegido);

  return (
    <main className="envoltorio pagina-medicamento">
      <a className="volver" href="#/" onClick={volver}>
        ← {hayBusqueda ? "Volver a los resultados" : "Buscar otro medicamento"}
      </a>

      {error && <p className="aviso">{error}</p>}
      {!datos && !error && <p className="aviso">Cargando medicamento…</p>}

      {datos && (
        <>
          <header className="detalle-cabecera">
            <figure className="detalle-foto">
              {datos.url_imagen ? (
                <img src={datos.url_imagen} alt="" />
              ) : (
                <span className="sin-foto">Sin fotografía</span>
              )}
            </figure>
            <div>
              <h1 className="detalle-titulo">
                {capitalizar(datos.principio_activo)}{" "}
                {legibleConcentracion(datos.concentracion)}
              </h1>
              <p className="detalle-bajada">
                {capitalizar(NOMBRE_FAMILIA[datos.familia] || datos.familia)}
              </p>
              <div className="detalle-datos">
                <span>
                  Desde <strong>{pesos(datos.precio_desde)}</strong>
                </span>
                <span>
                  {datos.farmacias.length}{" "}
                  {datos.farmacias.length === 1 ? "farmacia" : "farmacias"}
                </span>
                {datos.hay_bioequivalente && (
                  <span className="sello-bio declarado">
                    <span className="punto" />
                    Hay bioequivalentes
                  </span>
                )}
              </div>
            </div>
          </header>

          <section className="bloque">
            <h2 className="paso">¿Qué cantidad necesitas?</h2>
            <p className="paso-ayuda">
              Los precios solo se comparan entre envases del mismo tamaño.
            </p>
            <div className="tamanios">
              {datos.tamanios.map((t) => (
                <button
                  key={t.clave_equivalencia}
                  className="tamanio"
                  aria-pressed={elegido === t.clave_equivalencia}
                  onClick={() => setElegido(t.clave_equivalencia)}
                >
                  <div className="tamanio-cantidad">
                    {t.cantidad_envase} {t.unidad_envase}
                  </div>
                  <div className="tamanio-dato">
                    {pesos(t.precio_min)}
                    {t.farmacias > 1 && ` · ${t.farmacias} farmacias`}
                  </div>
                </button>
              ))}
            </div>
          </section>

          {elegido && (
            <div className="columnas">
              <section className="bloque">
                <h2 className="paso">Dónde comprarlo</h2>
                <p className="paso-ayuda">
                  {tamanio && `Envase de ${tamanio.cantidad_envase} ${tamanio.unidad_envase}, `}
                  ordenado del más barato al más caro.
                </p>
                <Comparacion clave={elegido} />
              </section>

              <section className="bloque">
                <h2 className="paso">Precio histórico</h2>
                <p className="paso-ayuda">
                  El precio más bajo disponible entre todas las farmacias en
                  cada fecha de medición.
                </p>
                <Historial clave={elegido} />
              </section>
            </div>
          )}
        </>
      )}
    </main>
  );
}

/* --------------------- Página de inicio --------------------- */

function PaginaInicio({ busqueda, cobertura }) {
  const { consulta, setConsulta, resultados, buscando, error, buscar } = busqueda;

  return (
    <>
      <section className="portada">
        <div className="portada-contenido">
          <span className="portada-etiqueta">Mismo medicamento, mejor precio</span>
          <h1>¿Qué medicamento necesitas?</h1>
          <p className="portada-bajada">
            Busca por nombre o principio activo y compara entre farmacias el
            precio del mismo medicamento, en la misma dosis y cantidad.
          </p>

          <div className="buscador">
            <span className="buscador-icono" aria-hidden="true">⌕</span>
            <input
              value={consulta}
              onChange={(e) => setConsulta(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && buscar()}
              placeholder="Ej: paracetamol, losartán, omeprazol…"
              aria-label="Buscar medicamento"
            />
            <button onClick={() => buscar()} disabled={consulta.trim().length < 3}>
              Buscar
            </button>
          </div>

          <div className="sugerencias">
            <span>Búsquedas frecuentes:</span>
            {["paracetamol", "ibuprofeno", "omeprazol", "losartan"].map((t) => (
              <button key={t} onClick={() => buscar(t)}>
                {t}
              </button>
            ))}
          </div>

          {cobertura && (
            <div className="cifras">
              <div>
                <strong>{cobertura.productos.toLocaleString("es-CL")}</strong>
                <span>productos</span>
              </div>
              <div>
                <strong>{cobertura.grupos_multiples.toLocaleString("es-CL")}</strong>
                <span>comparables entre farmacias</span>
              </div>
              <div>
                <strong>{cobertura.medicamentos_isp.toLocaleString("es-CL")}</strong>
                <span>medicamentos del ISP</span>
              </div>
            </div>
          )}
        </div>
      </section>

      <main className="envoltorio">
        {error && (
          <p className="aviso">
            <strong>No hay conexión con el servidor</strong>
            {error}
          </p>
        )}

        {buscando && <p className="aviso">Buscando…</p>}

        {resultados && !buscando && resultados.total === 0 && (
          <p className="aviso">
            <strong>Sin resultados para "{resultados.consulta}"</strong>
            Prueba con el principio activo en lugar del nombre comercial.
          </p>
        )}

        {resultados && !buscando && resultados.total > 0 && (
          <>
            <div className="encabezado-seccion">
              <h2>
                {resultados.total}{" "}
                {resultados.total === 1 ? "presentación" : "presentaciones"} de{" "}
                {resultados.consulta}
              </h2>
              <p>Elige una para ver precios e historial</p>
            </div>

            <div className="rejilla">
              {resultados.presentaciones.map((p) => (
                <Tarjeta
                  key={p.clave_presentacion}
                  datos={p}
                  href={enlaceMedicamento(p.clave_presentacion)}
                />
              ))}
            </div>
          </>
        )}
      </main>
    </>
  );
}

/* --------------------- Aplicación --------------------- */

export default function App() {
  const rutaActual = useRuta();
  const [consulta, setConsulta] = useState("");
  const [resultados, setResultados] = useState(null);
  const [buscando, setBuscando] = useState(false);
  const [error, setError] = useState(null);
  const [cobertura, setCobertura] = useState(null);

  useEffect(() => {
    fetch(`${API}/estadisticas`)
      .then((r) => r.json())
      .then(setCobertura)
      .catch(() => {});
  }, []);

  function buscar(termino) {
    const q = (termino ?? consulta).trim();
    if (q.length < 3) return;

    setConsulta(q);
    setBuscando(true);
    setError(null);

    fetch(`${API}/buscar?q=${encodeURIComponent(q)}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d) => {
        setResultados(d);
        // Si hay una sola presentacion no hay nada que elegir: se abre
        // directamente
        if (d.total === 1) {
          window.location.hash = enlaceMedicamento(d.presentaciones[0].clave_presentacion);
        }
      })
      .catch(() =>
        setError(
          "No se pudo conectar con el servidor. Revisa que la API esté corriendo en el puerto 8000."
        )
      )
      .finally(() => setBuscando(false));
  }

  return (
    <>
      <header className="barra">
        <a className="marca" href="#/">
          <span className="marca-icono" aria-hidden="true">+</span>
          bio<span>equi</span>
        </a>
        <div className="barra-lema">Compara precios de medicamentos en Chile</div>
      </header>

      {rutaActual.pagina === "medicamento" ? (
        <PaginaMedicamento clave={rutaActual.clave} hayBusqueda={resultados != null} />
      ) : (
        <PaginaInicio
          cobertura={cobertura}
          busqueda={{ consulta, setConsulta, resultados, buscando, error, buscar }}
        />
      )}

      <footer className="pie">
        <p>
          Los precios corresponden a la fecha de muestreo indicada en cada
          producto y pueden haber cambiado. BioEqui no vende medicamentos: los
          enlaces llevan al sitio de cada farmacia.
        </p>
        <p>
          La información es referencial y no reemplaza la indicación de un
          profesional de la salud. Existen medicamentos en los que la
          sustitución requiere supervisión médica.
        </p>
      </footer>
    </>
  );
}
