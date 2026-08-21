%% 압력용기 응력 시각화
%  그림 두 장을 만든다
%    pv_stress.svg    r/t 에 따른 원주응력 / 길이방향응력
%    pv_hoop_map.png  원통 표면 원주응력 분포 (뚜껑 근처 끝단 효과 포함)
%
%  실행 후 두 파일을 vault 의 assets 폴더로 옮기면 사이트에 바로 반영된다.

clear; clc; close all;
set(0, 'DefaultAxesFontName', 'Malgun Gothic');

P  = 2;      % 내압 [MPa]
Sy = 250;    % 항복강도 [MPa]
r  = 150;    % 안쪽 반지름 [mm]
t  = 3;      % 두께 [mm]
nu = 0.3;    % 포아송비


%% 그림 1 : r/t 에 따른 두 응력
rt = 5:0.5:150;
s1 = P .* rt;        % 원주응력      Pr/t
s2 = P .* rt / 2;    % 길이방향응력  Pr/2t

f1 = figure('Color', 'w', 'Position', [100 100 720 460]);
hold on; grid on; box on;

% 얇은 벽 가정이 깨지는 구간
fill([5 10 10 5], [0 0 400 400], [.92 .92 .92], 'EdgeColor', 'none');

h1 = plot(rt, s1, 'LineWidth', 2.2, 'Color', [.85 .33 .10]);
h2 = plot(rt, s2, 'LineWidth', 2.2, 'Color', [0 .45 .74]);
yline(Sy, '--', 'LineWidth', 1.2, 'Color', [.4 .4 .4]);
text(8, Sy + 16, '항복강도 250 MPa', 'FontName', 'Malgun Gothic', ...
     'Color', [.4 .4 .4]);

% 원주응력이 항복에 닿는 지점
rtf = Sy / P;
plot(rtf, Sy, 'o', 'MarkerSize', 8, 'LineWidth', 1.8, ...
     'MarkerEdgeColor', [.85 .33 .10], 'MarkerFaceColor', 'w');
text(rtf - 5, Sy - 32, sprintf('r/t = %.0f', rtf), ...
     'FontName', 'Malgun Gothic', 'HorizontalAlignment', 'right');

xlabel('r / t'); ylabel('응력 [MPa]');
title('내압 2 MPa 일 때 r/t 에 따른 응력');
legend([h1 h2], {'원주응력  \sigma_1 = Pr/t', ...
                 '길이방향응력  \sigma_2 = Pr/2t'}, ...
       'Location', 'northwest', 'FontName', 'Malgun Gothic');
xlim([5 150]); ylim([0 400]);

exportgraphics(f1, 'pv_stress.svg', 'ContentType', 'vector');


%% 그림 2 : 원통 표면 원주응력 분포
%  뚜껑이 벽의 팽창을 붙잡아서 끝단 근처는 이론값을 벗어난다
L  = 200;                                  % 뚜껑에서부터의 거리 [mm]
b  = (3 * (1 - nu^2))^0.25 / sqrt(r * t);  % 경계층 계수
x  = linspace(0, L, 260);
sh = P * r / t * (1 - exp(-b*x) .* (cos(b*x) + sin(b*x)));

th = linspace(0, 2*pi, 140);
[X, TH] = meshgrid(x, th);
Y = r * cos(TH);
Z = r * sin(TH);
C = repmat(sh, numel(th), 1);

f2 = figure('Color', 'w', 'Position', [100 100 940 500]);
surf(X, Y, Z, C, 'EdgeColor', 'none');
axis equal off;
view(-34, 18);
camlight headlight; lighting gouraud; material dull;
colormap(jet);
cb = colorbar;
cb.Label.String = '원주응력 [MPa]';
cb.Label.FontName = 'Malgun Gothic';
cb.FontName = 'Malgun Gothic';
title(sprintf('원통 표면 원주응력   P = %g MPa,  r = %g mm,  t = %g mm', P, r, t), ...
      'FontName', 'Malgun Gothic');

exportgraphics(f2, 'pv_hoop_map.png', 'Resolution', 180);


%% 확인용 출력
fprintf('중앙부 원주응력      %.1f MPa\n', P*r/t);
fprintf('중앙부 길이방향응력  %.1f MPa\n', P*r/(2*t));
fprintf('끝단 효과가 잦아드는 거리  약 %.0f mm\n', 3/b);
fprintf('안전계수 2 를 만족하는 r/t  <= %.1f\n', Sy/(2*P));
